# Catalog module

Owns stable anime identities, imported metadata, aliases, and the bounded
Bangumi search cache. Other modules consume only DTOs from `api.py`.

It does not parse release titles, rank candidates, or create download decisions.
External metadata is advisory: local anime records and aliases remain usable
when Bangumi is unavailable.
