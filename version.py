"""Single source of truth for the application version.

Kept in step with the git tag that publishes a release: the Build workflow
rewrites ``__version__`` from the tag before packaging, so a downloaded build
always reports the tag it was built from. Bump this by hand when tagging so
source runs report something sensible too.
"""

__version__ = "0.3.1"
