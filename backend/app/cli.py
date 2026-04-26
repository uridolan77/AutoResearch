"""`ar` CLI — entry point for operator commands.

Phase 1 commands wired here:
    ar secrets keygen
    ar secrets add NAME [VALUE]      (value read from stdin if omitted)
    ar secrets list
    ar secrets remove NAME
"""
from __future__ import annotations

import sys

import typer

from app.core.db import SessionLocal
from app.secrets import (
    SecretError,
    delete_secret,
    generate_key,
    list_secret_names,
    put_secret,
)

app = typer.Typer(help="AutoResearch Platform CLI")
secrets_app = typer.Typer(help="Encrypted secret store (AES-256-GCM)")
app.add_typer(secrets_app, name="secrets")


@secrets_app.command("keygen")
def keygen() -> None:
    """Print a new base64-encoded 32-byte key for AR_SECRET_KEY."""
    typer.echo(generate_key())


@secrets_app.command("add")
def add(
    name: str = typer.Argument(..., help="Logical secret name (e.g. OPENAI_API_KEY)"),
    value: str | None = typer.Argument(
        None, help="Secret value (omit to read from stdin)"
    ),
) -> None:
    """Encrypt and store a secret. Value is never echoed back."""
    if value is None:
        if sys.stdin.isatty():
            value = typer.prompt(f"Value for {name}", hide_input=True)
        else:
            value = sys.stdin.read().rstrip("\n")
    if not value:
        typer.echo("error: empty secret value", err=True)
        raise typer.Exit(code=1)
    db = SessionLocal()
    try:
        put_secret(db, name, value)
    except SecretError as e:
        typer.echo(f"error: {e}", err=True)
        raise typer.Exit(code=1) from e
    finally:
        db.close()
    typer.echo(f"stored: {name}")


@secrets_app.command("list")
def list_cmd() -> None:
    """List secret names. Values are never returned."""
    db = SessionLocal()
    try:
        names = list_secret_names(db)
    finally:
        db.close()
    if not names:
        typer.echo("(no secrets)")
        return
    for n in names:
        typer.echo(n)


@secrets_app.command("remove")
def remove(name: str) -> None:
    db = SessionLocal()
    try:
        ok = delete_secret(db, name)
    finally:
        db.close()
    if not ok:
        typer.echo(f"not found: {name}", err=True)
        raise typer.Exit(code=1)
    typer.echo(f"removed: {name}")


if __name__ == "__main__":
    app()
