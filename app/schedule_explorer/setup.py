from setuptools import setup, find_packages

setup(
    name="flixbus",
    version="0.1.0",
    packages=find_packages(),
    install_requires=[
        "fastapi",
        "uvicorn",
        "pandas",
        "pydantic",
        "msgpack>=1.0.5",
        "psutil>=5.9.0"
    ],
) 