from setuptools import setup, find_packages

setup(
    name="transit_providers",
    version="0.1.0",
    packages=find_packages(),
    install_requires=[
        "mobility-db-api>=0.1.1",
        "gtfs-realtime-bindings>=1.0.0",
        "httpx>=0.27.2",
        "python-dotenv>=1.0.0",
    ],
    python_requires=">=3.9",
) 
