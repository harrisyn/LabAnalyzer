from setuptools import setup, find_packages

setup(
    name="labSync",
    version="1.0.0",
    packages=find_packages(),
    install_requires=[
        'aiohttp>=3.8.0',
        'numpy>=1.21.0',
        'matplotlib>=3.4.0',
        'croniter>=1.0.0',
        'asyncio>=3.4.3',
        'nest_asyncio>=1.5.0',
    ],
    entry_points={
        'console_scripts': [
            'analyzer=src.main:main',
        ],
    },
    author="Harrison Hammond",
    author_email="harrisyn@gmail.com",
    description="Medical Analyzer Interface for ASTM protocol devices",
    long_description=open('README.md').read(),
    long_description_content_type="text/markdown",
    keywords="medical analyzer, ASTM, laboratory",
    url="https://github.com/harrisyn/labSync",
    classifiers=[
        "Development Status :: 4 - Beta",
        "Intended Audience :: Healthcare Industry",
        "Programming Language :: Python :: 3.8",
        "Programming Language :: Python :: 3.9",
        "Programming Language :: Python :: 3.10",
    ],
    python_requires='>=3.8',
)