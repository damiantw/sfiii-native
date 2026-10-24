"""Native re-implementation of the Shining Force III Translation Project patch wizard.

The package reproduces what the official .NET PatchWizard does to a Saturn disc (patch
selection, DFR byte patches, whole-file replacements, the rebuilt ISO 9660 image, IP.BIN and
the BIN/CUE it writes) without Windows, Wine or the wizard's code.  No game data or patch
files ship with it: patches are downloaded at run time or read from a package the user has.
"""

__version__ = "0.1.0"
