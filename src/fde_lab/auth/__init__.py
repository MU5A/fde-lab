"""Auth bridge: verifies identity-provider tokens and enforces role- and tenant-based access.

Install the extra with `pip install -e ".[auth]"`. The token logic in `tokens` needs only PyJWT,
so it imports without the web framework.
"""
