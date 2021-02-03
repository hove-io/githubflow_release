#!/usr/bin/env python
# -*- coding: utf-8 -*-

import githubflow_release

from setuptools import setup

requirements = [
    'docopt==0.6.2',
    'gitdb2==2.0.6',
    'GitPython==2.1.15',
    'requests==2.24.0',
    'semver==2.13.0'
]

version = '0.0.3'  # TODO use git tag ;)

setup(
    name='githubflow_release',
    version=version,
    description="github flow release",
    author="Antoine Desbordes",
    author_email='antoine.desbordes@gmail.com',
    url='https://github.com/CanalTP/githubflow_release',
    packages=[
        'githubflow_release',
    ],
    package_dir={'githubflow_release': 'githubflow_release'},
    include_package_data=True,
    install_requires=requirements,
    license="MIT",
    zip_safe=False,
    keywords='cli',
    classifiers=[
        'Intended Audience :: Developers',
        'License :: OSI Approved :: BSD License',
        'Natural Language :: English',
        'Programming Language :: Python :: 3',
        'Programming Language :: Python :: 3.3',
        'Programming Language :: Python :: 3.4',
        'Programming Language :: Python :: 3.6',
    ],
    entry_points={'console_scripts': [
        'githubflow_release = githubflow_release.run:main',
    ]},
)

