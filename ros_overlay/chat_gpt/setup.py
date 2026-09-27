from setuptools import setup
setup(name='chat_gpt',version='0.1.0',packages=['chat_gpt'],
 data_files=[('share/ament_index/resource_index/packages',['resource/chat_gpt']),('share/chat_gpt',['package.xml'])],
 entry_points={'console_scripts':["chat_gpt_service = guardrailgen.simulation.stack:service_main"]})

