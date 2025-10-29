from setuptools import setup, find_packages

setup(
    name="schedule_explorer",
    version="0.1.0",
    packages=find_packages(),
    install_requires=[
        "fastapi>=119.0",
        "uvicorn",
        "pandas",
        "pytest",
        "pytest-asyncio",
        "httpx",
        "mobility-db-api",
    ],
) 
