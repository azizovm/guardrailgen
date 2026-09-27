"""Reference semantics, strict boundaries, fail-closed validation and repair."""
import copy
import json
from fractions import Fraction

import pytest

from guardrailgen.api.cli import main
from guardrailgen.artifacts import build_artifact,monitor_from_artifact,save_artifact,load_monitor
from guardrailgen.schema import Rule,Scenario,RuleValidationError,compile_rule
from guardrailgen.validation import validate_rule
from guardrailgen.validation import equivalence as eq
from guardrailgen.compiler import Compiler
from test_compiler import FakeBackend,candidate,TEXT


@pytest.fixture
def scenario():
    return Scenario.from_dict({'schema_version':'1.0','frame':'odom','footprint_radius':.25,
        'regions':{'kitchen':{'kind':'rectangle','xmin':0,'xmax':2,'ymin':0,'ymax':2}},
        'supported_variables':['command.linear_speed','state.linear_speed','state.x','state.y']})


@pytest.fixture
def solver():
    return pytest.importorskip('z3')


def atom(op='le',value=.2,variable='command.linear_speed'):
    return {'op':'compare','variable':variable,'comparator':op,'value':value,'unit':'m/s'}


def rule(expression,scenario):
    return Rule.from_dict({'schema_version':'1.0','id':'reference','text':TEXT,'expression':expression},scenario)


def domains():
    return {'command.linear_speed':{'min':-.5,'max':.5,'unit':'m/s'}}


def test_rearranged_demorgan_predicates_are_equivalent(scenario,solver):
    a=rule({'op':'and','args':[atom('ge',-.2),atom()]},scenario)
    b=rule({'op':'not','arg':{'op':'or','args':[atom('lt',-.2),atom('gt',.2)]}},scenario)
    result=eq.check_equivalence(a,b,scenario,domains())
    assert result['status']=='equivalent'
    assert not result['english_semantics_verified']
    assert not result['floating_point_implementation_verified']


def test_exact_strict_boundary_counterexample_replays(scenario,solver):
    a=rule(atom('lt'),scenario);b=rule(atom(),scenario)
    result=eq.check_equivalence(a,b,scenario,domains())
    witness=result['counterexample']
    assert result['status']=='not_equivalent'
    assert Fraction(witness['exact_values']['command.linear_speed'])==Fraction(1,5)
    assert witness['candidate']=='UNSAFE' and witness['reference']=='SAFE'
    assert witness['float_replay_verified']
    assert compile_rule(a,scenario).evaluate(witness['approximate_values'])!=compile_rule(b,scenario).evaluate(witness['approximate_values'])


def test_missing_negative_speed_bound_is_found(scenario,solver):
    a=rule(atom(),scenario)
    b=rule({'op':'and','args':[atom(),atom('ge',-.2)]},scenario)
    result=eq.check_equivalence(a,b,scenario,domains())
    assert result['counterexample']['approximate_values']['command.linear_speed']<-.2
    assert result['counterexample']['reference']=='UNSAFE'
    # Domain restrictions change what is established, and must be in evidence.
    positive={'command.linear_speed':{'min':0,'max':.5,'unit':'m/s'}}
    result2=eq.check_equivalence(a,b,scenario,positive)
    assert result2['status']=='equivalent' and result2['inputs_sha256']!=result['inputs_sha256']


def test_state_and_input_cannot_be_conflated(scenario,solver):
    d=domains();d['state.linear_speed']=d['command.linear_speed'].copy()
    result=eq.check_equivalence(rule(atom(),scenario),rule(atom(variable='state.linear_speed'),scenario),scenario,d)
    assert result['status']=='not_equivalent' and result['counterexample']['float_replay_verified']


@pytest.mark.parametrize('bad',[{}, {'unknown':{'min':0,'max':1,'unit':'m/s'}},
    {'command.linear_speed':{'min':1,'max':0,'unit':'m/s'}},
    {'command.linear_speed':{'min':False,'max':1,'unit':'m/s'}},
    {'command.linear_speed':{'min':0,'max':float('inf'),'unit':'m/s'}},
    {'command.linear_speed':{'min':0,'max':1,'unit':'km/h'}},
    {'state.x':{'min':0,'max':1,'unit':'m'}},
    {'command.linear_speed':[0,1]}])
def test_invalid_or_missing_domains_never_prove_equivalence(scenario,bad):
    a=rule(atom(),scenario)
    with pytest.raises(ValueError):
        eq.check_equivalence(a,a,scenario,bad)


def test_single_point_domain_is_nonempty_and_boundary_sensitive(scenario,solver):
    d=domains();d['command.linear_speed'].update(min=.2,max=.2)
    assert eq.check_equivalence(rule(atom('lt'),scenario),rule(atom(),scenario),scenario,d)['status']=='not_equivalent'


def test_geometry_is_explicitly_unsupported_even_for_identical_trees(scenario):
    a=rule({'op':'not','arg':{'op':'inside','region':'kitchen'}},scenario)
    report=validate_rule(a,scenario,reference=a,domains=domains())
    assert report['equivalence']['status']=='unsupported' and report['errors']


def test_unavailable_solver_is_not_success(scenario,monkeypatch):
    def unavailable():
        raise ImportError('fixture')
    monkeypatch.setattr(eq,'_load_z3',unavailable)
    a=rule(atom(),scenario)
    report=validate_rule(a,scenario,reference=a,domains=domains())
    assert report['equivalence']['status']=='unavailable' and report['errors']


def test_timeout_is_unknown_and_artifact_is_not_accepted(scenario,solver,monkeypatch):
    class Timeout:
        def set(self,**kw):
            assert kw=={'timeout':10}
        def add(self,*args): pass
        def check(self): return solver.unknown
        def reason_unknown(self): return 'timeout'
    monkeypatch.setattr(solver,'SolverFor',lambda logic,**kw:Timeout())
    a=rule(atom(),scenario)
    report=validate_rule(a,scenario,reference=a,domains=domains(),solver_timeout_ms=10)
    assert report['equivalence']['status']=='unknown'
    assert report['equivalence']['reason']=='timeout' and report['errors']
    with pytest.raises(RuleValidationError):
        monitor_from_artifact(build_artifact(a,scenario,report))


@pytest.mark.parametrize('timeout',[0,-1,True,1.5,60001])
def test_invalid_timeout_rejected(scenario,timeout):
    a=rule(atom(),scenario)
    with pytest.raises(ValueError):
        eq.check_equivalence(a,a,scenario,domains(),timeout_ms=timeout)


def test_saved_proof_is_rechecked_not_trusted(scenario,solver,tmp_path):
    a=rule(atom(),scenario)
    report=validate_rule(a,scenario,reference=a,domains=domains())
    artifact=build_artifact(a,scenario,report)
    path=save_artifact(artifact,tmp_path)
    assert load_monitor(path).name==a.id
    # Even an unsigned, internally consistent altered artifact cannot reuse
    # the passing reference evidence for a looser candidate.
    b=rule(atom('le',.4),scenario)
    forged=build_artifact(b,scenario,report)
    with pytest.raises(RuleValidationError,match='equivalence revalidation'):
        monitor_from_artifact(forged)
    altered=copy.deepcopy(artifact)
    altered['validation']['equivalence']['domains']['command.linear_speed']['min']=0
    with pytest.raises(RuleValidationError,match='equivalence revalidation'):
        monitor_from_artifact(altered)


def test_solver_failure_on_reload_cannot_be_ignored(scenario,solver,monkeypatch):
    a=rule(atom(),scenario)
    report=validate_rule(a,scenario,reference=a,domains=domains())
    def unavailable(): raise ImportError()
    monkeypatch.setattr(eq,'_load_z3',unavailable)
    with pytest.raises(RuleValidationError,match='equivalence revalidation'):
        monitor_from_artifact(build_artifact(a,scenario,report))


def test_counterexample_drives_bounded_repair_without_reference_answer_leak(scenario,solver):
    good=candidate();bad=copy.deepcopy(good)
    bad['rule']['expression']=atom()
    reference=Rule.from_dict(good['rule'],scenario)
    backend=FakeBackend(bad,good)
    result=Compiler(backend,scenario,validator=lambda r,s:validate_rule(r,s,reference=reference,domains=domains())).compile(TEXT)
    assert result.ok and len(result.attempts)==2
    assert result.attempts[0]['validation']['equivalence']['reference_rule']==reference.to_dict()
    repair=backend.calls[1][0][-1]['content']
    assert 'counterexample' in repair and 'reference_rule' not in repair
    assert result.artifact['validation']['additional_validation']['equivalence']['status']=='equivalent'
    assert not result.artifact['validation']['english_semantics_verified']


def test_cli_rejects_mismatch_without_writing_artifact_then_accepts_equivalence(scenario,solver,tmp_path,capsys):
    files={'scenario':scenario.to_dict(),'reference':rule(atom(),scenario).to_dict(),
           'candidate':rule(atom('lt'),scenario).to_dict(),'domains':domains()}
    for name,data in files.items():
        (tmp_path/(name+'.json')).write_text(json.dumps(data))
    args=['validate',str(tmp_path/'candidate.json'),'--scenario',str(tmp_path/'scenario.json'),
          '--reference',str(tmp_path/'reference.json'),'--domains',str(tmp_path/'domains.json'),
          '--output-dir',str(tmp_path/'artifacts')]
    assert main(args)==2
    assert json.loads(capsys.readouterr().out)['validation']['equivalence']['status']=='not_equivalent'
    assert not (tmp_path/'artifacts').exists()
    (tmp_path/'candidate.json').write_text(json.dumps(files['reference']))
    assert main(args)==0
    assert json.loads(capsys.readouterr().out)['validation']['equivalence']['status']=='equivalent'


def test_cli_missing_domains_fails_before_hosted_request(scenario,tmp_path,capsys):
    (tmp_path/'scenario.json').write_text(json.dumps(scenario.to_dict()))
    (tmp_path/'reference.json').write_text(json.dumps(rule(atom(),scenario).to_dict()))
    assert main(['compile',TEXT,'--scenario',str(tmp_path/'scenario.json'),
        '--reference',str(tmp_path/'reference.json')])==2
    assert 'must be supplied together' in json.loads(capsys.readouterr().out)['message']


def test_cli_unsupported_equivalence_never_contacts_model(scenario,tmp_path,capsys,monkeypatch):
    from guardrailgen.api import cli
    def unexpected(*args,**kwargs):
        pytest.fail('Model backend must not be created for an unsupported reference check')
    monkeypatch.setattr(cli,'GroqBackend',unexpected)
    a=rule({'op':'inside','region':'kitchen'},scenario)
    for name,data in [('scenario',scenario.to_dict()),('reference',a.to_dict()),('domains',domains())]:
        (tmp_path/(name+'.json')).write_text(json.dumps(data))
    assert main(['compile',TEXT,'--scenario',str(tmp_path/'scenario.json'),'--reference',
                 str(tmp_path/'reference.json'),'--domains',str(tmp_path/'domains.json')])==2
    assert json.loads(capsys.readouterr().out)['validation']['equivalence']['status']=='unsupported'


def test_unrepresentable_witness_is_not_mislabeled_as_float_replay(scenario,solver):
    d=domains();d['command.linear_speed'].update(min=2**53,max=2**53+2)
    result=eq.check_equivalence(rule(atom('lt',2**53+1),scenario),
        rule(atom('le',2**53+1),scenario),scenario,d)
    assert result['status']=='not_equivalent'
    assert result['counterexample']['float_replay_verified'] is False


def test_concurrent_checks_use_independent_solver_contexts(scenario,solver):
    from concurrent.futures import ThreadPoolExecutor
    def run(i):
        return eq.check_equivalence(rule(atom('lt' if i%2 else 'le'),scenario),
            rule(atom(),scenario),scenario,domains())['status']
    with ThreadPoolExecutor(max_workers=2) as pool:
        assert list(pool.map(run,range(4)))==['equivalent','not_equivalent']*2
