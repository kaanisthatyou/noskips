"""Accounts, handles, and getting a widget signed in without ever handing it a
secret.

Four ways in, three of them ordinary:

  * Google and Discord, through the browser (oauth.py)
  * email + password, with verification (passwords.py, tokens.py)
  * and the interesting one: a paired desktop widget (pairing.py), which logs
    in by *delegating to the browser* rather than by holding credentials.
"""
