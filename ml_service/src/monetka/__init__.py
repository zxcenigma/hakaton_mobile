"""Monetka data & ML platform.

Supporting data infrastructure for «Монетка» — an offline-first Android app that
teaches children aged 7-11 to plan a budget, separate needs from wants and save
towards a goal, using a virtual pet as feedback.

Design constraints inherited from the customer's technical specification
(Департамент финансов города Москвы):

* the mandatory game loop runs fully offline, on-device (§3.1.5);
* no personal data of the child or the adult is collected (§3.5);
* ML is optional and, where used, must declare which task it solves, which data
  it processes and how correctness is controlled (§3.2);
* if a server side exists, it is described by an OpenAPI spec and starts with a
  single documented procedure, preferably Docker Compose (§3.2).

Everything in this package therefore operates on **synthetic telemetry** or on
**opt-in, pseudonymous, aggregate** game events — never on raw personal data.
"""

__version__ = "0.1.0"
