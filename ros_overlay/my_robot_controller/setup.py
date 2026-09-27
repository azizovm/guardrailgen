from setuptools import setup
setup(name='my_robot_controller',version='0.1.0',packages=['my_robot_controller'],
 data_files=[('share/ament_index/resource_index/packages',['resource/my_robot_controller']),('share/my_robot_controller',['package.xml'])],
 entry_points={'console_scripts':["LLM_robot_controller = guardrailgen.simulation.stack:controller_main","safety_check_nonlinear_reachability = guardrailgen.simulation.stack:filter_main"]})

