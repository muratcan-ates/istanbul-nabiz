"""The Nabız product app: the citizen face (``/``) and the simulated operator's console (``/console``).

One FastAPI process, default port 8090, started with ``python -m nabiz.console`` or
``make console``. It is a composition root: it builds the one :class:`~ibb_mcp.tools.Nabiz`
facade the process shares, wires :class:`nabiz.agent.NabizAgent` into the streamed chat, and
reaches the decision core (``nexus_core``) and the step-free alternative only through the
ports in :mod:`nabiz.console.ports`, which the integrator binds to their real implementations.

Modules:

- :mod:`~nabiz.console.app`       the app factory, the process entry point and the citizen routes
- :mod:`~nabiz.console.chat`      ``POST /api/chat``: the agent turn, streamed as server-sent events
- :mod:`~nabiz.console.policy`    what the chat refuses, which needs it passes on, what it offers to remember
- :mod:`~nabiz.console.budget`    the daily spend ceiling for the paid model
- :mod:`~nabiz.console.arrival`   the single-minute arrival rule
- :mod:`~nabiz.console.brief`     the home page's city cards
- :mod:`~nabiz.console.cards`     the contract's Provenance and Card shapes
- :mod:`~nabiz.console.operator`  ``/api/console/*`` over the console port
- :mod:`~nabiz.console.ports`     the port protocols and their not-yet-wired defaults
- :mod:`~nabiz.console.envfile`   the ``.env`` loader the entry point runs, and nothing else
"""
