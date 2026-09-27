import os
from glob import glob
from setuptools import find_packages, setup

package_name = 'guardrailgen'

setup(
    name=package_name,
    version='0.1.0',
    packages=find_packages(exclude=['test']),
    data_files=[
        ('share/ament_index/resource_index/packages',
         ['resource/' + package_name]),
        ('share/' + package_name, ['package.xml']),
        (os.path.join('share', package_name, 'launch'),
         glob('launch/*.launch.py')),
        (os.path.join('share', package_name, 'rules'),
         glob('rules/*.yaml')),
    ],
    python_requires='>=3.10',
    install_requires=['setuptools', 'PyYAML==6.0.3'],
    extras_require={'test': ['pytest==9.1.1'], 'validation': ['rtamt==0.3.5'],
                    'solver': ['z3-solver==4.15.3.0']},
    zip_safe=True,
    maintainer='Mahammad Azizov',
    maintainer_email='you@tum.de',
    description='NL safety rules -> runtime monitors for LLM-controlled robots (on top of SafeLLMRA).',
    license='TODO',
    tests_require=['pytest'],
    entry_points={
        'console_scripts': [
            'monitor_node = guardrailgen.monitor_node:main',
            'guardrailgen = guardrailgen.api.cli:main',
        ],
    },
)
