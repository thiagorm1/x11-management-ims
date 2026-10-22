from setuptools import setup, find_packages

setup(
    name="x11-management-ims",
    version="1.0.0",
    description="X11 Management IMS (Integrated Management System) — Hardware Control Suite",
    package_dir={"": "src"},
    packages=find_packages(where="src"),
    package_data={"x11_management": ["*.json"]},
    include_package_data=True,
    entry_points={
        "console_scripts": [
            "x11-management-ims=x11_management.cli:main",
            "x11-gui=x11_management.gui:run",
        ],
    },
)
