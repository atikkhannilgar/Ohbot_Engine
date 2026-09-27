"""Runs the BEAT2-trained audio -> Ohbot pose model against a real (or
simulated/console) controller. Separate from the chat pipeline: nothing here
is imported by ``obot.__main__`` unless this package is used directly, so the
base app never needs torch installed.
"""
