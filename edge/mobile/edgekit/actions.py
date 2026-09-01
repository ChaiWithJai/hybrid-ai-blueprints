"""Client-action registry — the ApiAction transplant.

violet_rails evals Ruby strings; Dart and Python cannot and should not.
Actions here are named, pre-registered callables configured by JSON params
in a bundle. A handler receives the resource's properties dict (mutable),
the params from the bundle, and a ctx dict carrying at least `provider`
and `store`. It returns nothing; it edits properties in place. Raising
aborts the create — a failed action must never half-write a resource.
"""


class ActionError(RuntimeError):
    pass


class ActionRegistry:
    def __init__(self):
        self._handlers = {}

    def register(self, name, fn):
        if name in self._handlers:
            raise ActionError(f"action {name!r} already registered")
        self._handlers[name] = fn
        return fn

    def action(self, name):
        """Decorator form: @registry.action('summarize')"""
        def wrap(fn):
            return self.register(name, fn)
        return wrap

    def run(self, name, properties, params, ctx):
        if name not in self._handlers:
            raise ActionError(f"unknown action {name!r}")
        self._handlers[name](properties, params or {}, ctx)

    def names(self):
        return sorted(self._handlers)
