from setuptools import setup, find_packages

setup(
    name="schedule_explorer",
    version="0.1.0",
    packages=find_packages(),
    install_requires=[
        "certifi>=2026.10.19",
        "fastapi>=0.140.13",
        "uvicorn",
        "pandas",
        "pytest",
        "pytest-asyncio",
        "httpx",
        "mobility-db-api>=0.6.0",
    ],
) 
