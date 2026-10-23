from setuptools import setup, find_packages

setup(
    name="transit_providers",
    version="0.2.12",
    packages=find_packages(),
    install_requires=[
        "certifi>=2026.10.19",
        "mobility-db-api>=0.6.0",
        "gtfs-realtime-bindings>=2.0.0",
        "protobuf>=5.29.6,<8",
        "httpx>=0.27.2",
        "python-dotenv>=1.0.0",
    ],
    python_requires=">=3.9",
) 
