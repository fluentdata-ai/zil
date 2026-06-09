"""Zil CLI — entry point."""

import click

from zil import __version__
from zil.commands.audit import audit
from zil.commands.deploy import deploy
from zil.commands.eval import eval
from zil.commands.init import init
from zil.commands.inspect import inspect
from zil.commands.pack import pack
from zil.commands.push import push
from zil.commands.serve import serve
from zil.commands.topology import topology
from zil.commands.validate import validate


@click.group()
@click.version_option(version=__version__, prog_name="zil")
def cli() -> None:
    """Zil — A framework for production AI agents.

    Compose, validate, package, and inspect agent manifests built on
    ADK, A2A, MCP, and OpenTelemetry.
    """


cli.add_command(audit)
cli.add_command(init)
cli.add_command(validate)
cli.add_command(pack)
cli.add_command(inspect)
cli.add_command(eval)
cli.add_command(deploy)
cli.add_command(push)
cli.add_command(serve)
cli.add_command(topology)
