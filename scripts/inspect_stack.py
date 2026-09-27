"""Show experiment processes and only non-secret ROS/budget flags on Linux."""
import json
from pathlib import Path

allowed={b'ROS_DOMAIN_ID',b'GUARDRAILGEN_OFFLINE',b'GUARDRAILGEN_MODEL_CALL_LIMIT',
         b'GUARDRAILGEN_WAYPOINT_GUIDANCE'}
for path in Path('/proc').iterdir():
    if not path.name.isdecimal():
        continue
    try:
        command=path.joinpath('cmdline').read_bytes().replace(b'\0',b' ').decode()
        if '/lib/chat_gpt/chat_gpt_service' not in command and '/lib/my_robot_controller/' not in command:
            continue
        flags=[value.decode() for value in path.joinpath('environ').read_bytes().split(b'\0')
               if value.split(b'=',1)[0] in allowed]
        print(json.dumps({'pid':int(path.name),'command':command,'flags':flags}))
    except (OSError,UnicodeDecodeError):
        continue
