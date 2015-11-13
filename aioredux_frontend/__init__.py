import pbr.version

from .frontend import make_app  # noqa

__version__ = pbr.version.VersionInfo(
    'aioredux_frontend').version_string()
