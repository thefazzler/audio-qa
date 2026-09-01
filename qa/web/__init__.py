"""The web front door.

Two front doors, one engine. The pages here call the same service functions
the CLI calls; nothing in this package knows how to transcribe, align or build
a packet. If moving to a server changed only these files, the layering held.
"""
