"""The service and controller roles of the five-terminal SafeLLMRA workflow."""
import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import time

from guardrailgen.artifacts import read_json
from .controller import PLAN_SCHEMA, compact_navigation_messages, goal_seeking_plan, MotionHistory, paced_request_deadline, held_input_plan
from .episode import load_credentials, prepare_rule
from .groq_compat import GroqCompatibilityBackend
from .plans import validate_plan


def root_path():
    return Path(os.environ['GUARDRAILGEN_ROOT']).resolve()


def service_main():
    import rclpy
    from rclpy.node import Node
    from custom_msgs.srv import ChatPrompt
    root=root_path()
    cfg=read_json(root/'config/house_experiment.json')
    load_credentials(root/'.env')
    offline=os.environ.get('GUARDRAILGEN_OFFLINE')=='1'
    limit=int(os.environ.get('GUARDRAILGEN_MODEL_CALL_LIMIT','120'))

    class ModelService(Node):
        def __init__(self):
            super().__init__('guardrailgen_model_service')
            self.calls=0
            self.backend=GroqCompatibilityBackend(os.environ.get('GROQ_MODEL') or 'openai/gpt-oss-120b',timeout=20)
            self.navigation_backend=GroqCompatibilityBackend(os.environ.get('GROQ_MODEL') or 'openai/gpt-oss-120b',
                timeout=20,max_output_tokens=1024,reasoning_effort='low')
            self.create_service(ChatPrompt,'/chat_gpt_query',self.navigation)
            self.create_service(ChatPrompt,'/guardrailgen/compile_rule',self.compile)
            self.get_logger().info(f'Model service ready: {"OFFLINE smoke" if offline else "Groq openai/gpt-oss-120b"}; navigation cap={limit}')

        def compile(self,request,response):
            out=root/'runs'/datetime.now(timezone.utc).strftime('compilation_%Y%m%dT%H%M%S_%fZ')
            out.mkdir(parents=True)
            try:
                # This scenario's independent labels are specific to the kitchen invariant.
                # Other rules belong in the general compiler CLI with appropriate trace labels.
                if request.prompt.strip().rstrip('.').lower()!='never enter the kitchen':
                    raise ValueError('This experiment supports the labeled rule: Never enter the kitchen.')
                monitor,path=prepare_rule(root,cfg,out,'reference' if offline else 'groq',
                    text=request.prompt,backend=self.backend)
                result={'status':'validated','artifact':str(path),'stl':monitor.stl,
                    'source':'reference' if offline else 'groq','report_dir':str(out)}
            except Exception as exc:
                result={'status':'error','message':str(exc),'report_dir':str(out)}
            response.response=json.dumps(result)
            self.get_logger().info(response.response)
            return response

        def navigation(self,request,response):
            try:
                data=json.loads(request.prompt)
                if self.calls>=limit:
                    raise ValueError('Navigation request budget exhausted; restart explicitly for a new episode')
                if offline:
                    plan=goal_seeking_plan(data['pose'],data['goal'])
                    result={'plan':plan,'metadata':{'source':'offline_goal_seeking','model_call':False}}
                else:
                    self.calls+=1
                    messages=compact_navigation_messages(data)
                    answer=self.navigation_backend.generate(messages,PLAN_SCHEMA)
                    rows=answer.payload['plan']
                    plan=validate_plan([[row['v'],row['omega']] for row in rows])
                    if len(plan)!=5:
                        raise ValueError('Expected five navigation commands')
                    result={'plan':plan,'metadata':answer.metadata,'call':self.calls}
                self.get_logger().info(f'Navigation response {self.calls}/{limit}: {result["plan"]}')
            except Exception as exc:
                result={'error':str(exc),'call':self.calls}
                if getattr(exc,'status',None)=='rate_limited':
                    result['retry_after']=exc.retry_after_seconds
                self.get_logger().error(str(exc))
            response.response=json.dumps(result)
            return response

    rclpy.init(); node=ModelService()
    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    finally:
        node.destroy_node(); rclpy.shutdown()


def controller_main():
    import rclpy
    from rclpy.node import Node
    from custom_msgs.srv import ChatPrompt
    from std_msgs.msg import String,Float64MultiArray,MultiArrayDimension

    class Controller(Node):
        def __init__(self):
            super().__init__('guardrailgen_llm_controller')
            self.query=self.create_client(ChatPrompt,'/chat_gpt_query')
            self.control=self.create_client(ChatPrompt,'/guardrailgen/control')
            self.create_service(ChatPrompt,'/chat_gpt_ask',self.prompt)
            self.create_subscription(String,'/guardrailgen/observation',self.observe,10)
            self.pub=self.create_publisher(Float64MultiArray,'/parsed_plan',10)
            self.events=self.create_publisher(String,'/guardrailgen/controller_event',10)
            self.latest=None; self.received=0.; self.future=None; self.start_future=None
            self.running=False; self.plan_id=0; self.sent=False; self.task='Go to the goal.'
            self.history=MotionHistory()
            self.calls=0; self.limit=int(os.environ.get('GUARDRAILGEN_MODEL_CALL_LIMIT','120'))
            self.next_request_at=0.
            self.request_started_at=0.
            self.request_revision=0
            self.last_model_at=0.; self.tail=None
            self.held_suppressed=False
            self.queued_model=None
            self.hold_seconds=float(os.environ.get('GUARDRAILGEN_HOLD_SECONDS','3'))
            if not 0<=self.hold_seconds<=3:
                raise ValueError('GUARDRAILGEN_HOLD_SECONDS must be between 0 and 3')
            self.offline=os.environ.get('GUARDRAILGEN_OFFLINE')=='1'
            self.create_timer(0.1,self.tick)
            self.get_logger().info('Controller ready. Activate a rule, then prompt /chat_gpt_ask. No automatic motion.')

        def event(self,kind,**data):
            msg=String(); msg.data=json.dumps({'kind':kind,**data}); self.events.publish(msg)

        def prompt(self,request,response):
            if self.running or self.start_future is not None:
                response.response=json.dumps({'status':'error','message':'Episode already running'})
            elif not self.control.service_is_ready() or not self.query.service_is_ready():
                response.response=json.dumps({'status':'error','message':'Start terminals 2 and 4 first'})
            else:
                self.task=request.prompt
                req=ChatPrompt.Request(); req.prompt=json.dumps({'command':'start'})
                self.start_future=self.control.call_async(req)
                response.response=json.dumps({'status':'start_requested','task':self.task})
            return response

        def observe(self,msg):
            incoming=json.loads(msg.data)
            if self.latest is not None and incoming.get('target_revision',0)!=self.latest.get('target_revision',0):
                self.sent=False; self.tail=None; self.queued_model=None
                self.event('navigation_target_changed',goal=incoming['goal'],
                    target_revision=incoming.get('target_revision',0))
            self.latest=incoming; self.received=time.monotonic()
            if self.latest.get('end_reason'):
                self.running=False
            if self.running and self.latest.get('pose'):
                self.history.observe(self.latest['pose'],self.latest['executed'])

        def tick(self):
            self.event('heartbeat')
            if self.start_future is not None and self.start_future.done():
                result=json.loads(self.start_future.result().response)
                self.start_future=None
                self.running=result.get('status')=='started'
                if self.running:
                    self.sent=False; self.history.clear(); self.tail=None; self.queued_model=None
                self.get_logger().info('Episode start: '+json.dumps(result))
            if not self.running:
                return
            if not self.latest or time.monotonic()-self.received>1:
                self.event('failure',error='Filter observation expired'); self.running=False; return
            if self.sent and self.latest['last_plan_id']>=self.plan_id and self.latest['needs_plan']:
                self.sent=False
            if self.queued_model is not None and not self.sent and self.latest['needs_plan']:
                plan,metadata=self.queued_model; self.queued_model=None
                self.publish_plan(plan)
                self.event('response',plan_id=self.plan_id,plan=plan,metadata=metadata)
                return
            if self.future is not None:
                if not self.future.done():
                    self.offer_tail()
                    return
                try:
                    result=json.loads(self.future.result().response)
                    if 'retry_after' in result:
                        self.next_request_at=time.monotonic()+result['retry_after']
                        self.event('rate_limit_backoff',seconds=result['retry_after'])
                        self.future=None
                        return
                    if 'error' in result:
                        raise ValueError(result['error'])
                    plan=validate_plan(result['plan'])
                    tokens=(result.get('metadata',{}).get('usage') or {}).get('total_tokens',0)
                    self.next_request_at=max(self.next_request_at,
                        paced_request_deadline(self.request_started_at,time.monotonic(),tokens))
                    if self.request_revision!=self.latest.get('target_revision',0):
                        self.event('stale_target_response_discarded',request_revision=self.request_revision,
                            current_revision=self.latest.get('target_revision',0))
                    else:
                        self.queued_model=(plan,result.get('metadata'))
                        self.last_model_at=time.monotonic(); self.tail=plan[-1]
                        self.held_suppressed=False
                except Exception as exc:
                    self.event('failure',error=str(exc)); self.running=False
                self.future=None
                return
            if self.sent:
                if self.latest['last_plan_id']<self.plan_id or not self.latest['needs_plan']:
                    return
                self.sent=False
            if self.latest['needs_plan'] and self.latest['ready']:
                if time.monotonic()<self.next_request_at:
                    self.offer_tail()
                    return
                if self.calls>=self.limit:
                    self.event('failure',error='Navigation call budget reached'); self.running=False; return
                if not self.query.service_is_ready():
                    self.event('failure',error='Model service unavailable'); self.running=False; return
                self.calls+=1
                data={key:self.latest[key] for key in ('pose','goal','lidar','executed')}
                data['waypoint_guidance_enabled']=self.latest.get('waypoint_guidance_enabled',False)
                data['target_revision']=self.latest.get('target_revision',0)
                self.history.observe(self.latest['pose'],self.latest['executed'])
                data.update(task=self.task,history=self.history.checkpoint())
                req=ChatPrompt.Request(); req.prompt=json.dumps(data)
                # Log the exact simulated input for reproducible prompt audits.
                self.event('offline_request' if self.offline else 'request',call=self.calls,observation=data)
                self.request_started_at=time.monotonic()
                self.request_revision=self.latest.get('target_revision',0)
                self.future=self.query.call_async(req)

        def offer_tail(self):
            # Match the upstream streaming-control behavior, but with a bounded
            # lifetime. These are NEW held-input proposals, explicitly logged;
            # they never go directly to cmd_vel or skip the safety filter.
            if (self.sent or self.tail is None or not self.latest['needs_plan'] or not self.latest['ready'] or
                    time.monotonic()-self.last_model_at>=self.hold_seconds):
                return
            plan=held_input_plan(self.latest['pose'],self.latest['goal'],self.tail)
            if not plan:
                if not self.held_suppressed:
                    self.event('held_input_suppressed',command=self.tail,
                        reason='zero_input_or_extra_turn_would_overshoot_or_oppose_goal_bearing')
                    self.held_suppressed=True
                return
            self.publish_plan(plan)
            self.event('held_input_proposal',plan_id=self.plan_id,command=self.tail,
                model_response_age=time.monotonic()-self.last_model_at,lease_seconds=self.hold_seconds,
                policy='goal_heading_guard')

        def publish_plan(self,plan):
            self.plan_id+=1
            msg=Float64MultiArray(); msg.data=[float(v) for row in plan for v in row]
            dim=MultiArrayDimension(); dim.label=f'{self.plan_id}:{self.latest.get("target_revision",0)}'
            dim.size=len(plan); dim.stride=len(plan)*2
            msg.layout.dim=[dim]; self.pub.publish(msg); self.sent=True

    rclpy.init(); node=Controller()
    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    finally:
        node.event('failure',error='Controller stopped'); node.destroy_node(); rclpy.shutdown()


def filter_main():
    from .episode import main
    argv=['--root',str(root_path()),'--controller','external','--rule-source','service',
          '--max-model-calls',os.environ.get('GUARDRAILGEN_MODEL_CALL_LIMIT','120'),
          '--predictor',os.environ.get('GUARDRAILGEN_PREDICTOR','safellmra_body_frame_experimental'),
          '--seconds',os.environ.get('GUARDRAILGEN_EPISODE_SECONDS','180')]
    if os.environ.get('GUARDRAILGEN_WAYPOINT_GUIDANCE','1')=='1':
        argv.append('--waypoint-guidance')
    main(argv)


def prompt_main(argv=None):
    import rclpy
    from rclpy.node import Node
    from custom_msgs.srv import ChatPrompt
    parser=argparse.ArgumentParser(description='Prompt the four-terminal GuardrailGen/SafeLLMRA stack')
    parser.add_argument('command',choices=['rule','activate','go','status','stop'])
    parser.add_argument('text',nargs='?',default='')
    args=parser.parse_args(argv)
    rclpy.init(); node=Node('guardrailgen_prompt')

    def call(service,text):
        client=node.create_client(ChatPrompt,service)
        if not client.wait_for_service(timeout_sec=10):
            raise RuntimeError('Service unavailable: '+service)
        request=ChatPrompt.Request(); request.prompt=text
        future=client.call_async(request)
        rclpy.spin_until_future_complete(node,future,timeout_sec=100)
        if not future.done():
            raise RuntimeError('Service response timed out; check service terminal before retrying')
        result=json.loads(future.result().response)
        print(json.dumps(result,indent=2),flush=True)
        if result.get('status')=='error':
            raise RuntimeError(result.get('message','Service error'))
        return result

    try:
        if args.command=='rule':
            result=call('/guardrailgen/compile_rule',args.text or 'Never enter the kitchen.')
            call('/guardrailgen/control',json.dumps({'command':'activate','artifact':result['artifact']}))
        elif args.command=='activate':
            if not args.text:
                parser.error('activate requires an existing validated artifact path')
            call('/guardrailgen/control',json.dumps({'command':'activate','artifact':args.text}))
        elif args.command=='go':
            call('/chat_gpt_ask',args.text or 'Go to the goal.')
        else:
            call('/guardrailgen/control',json.dumps({'command':args.command}))
    finally:
        node.destroy_node(); rclpy.shutdown()


if __name__=='__main__':
    prompt_main()
