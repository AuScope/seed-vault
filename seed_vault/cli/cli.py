import os
import sys

import click

from seed_vault.service.seismoloader import run_main
from seed_vault.service.db import populate_database_from_sds
from seed_vault.service.db import clean_database

dirname = os.path.dirname(__file__)
par_dir = os.path.dirname(dirname)

CONTEXT_SETTINGS = {"help_option_names": ["-h", "--help"], "max_content_width": 100}


# --------------------------------------------------------------------------
# Help formatting helpers
#
# Click doesn't document positional arguments by itself, so commands use
# HelpArgument (an argument with a help text) and DocumentedCommand (adds an
# "Arguments" section and an "Examples" section to the help output).
# --------------------------------------------------------------------------
_CLICK_CALLS_FORMAT_ARGUMENTS = hasattr(click.Command, "format_arguments")


class HelpArgument(click.Argument):
    def __init__(self, *args, help: str = "", **kwargs):
        super().__init__(*args, **kwargs)
        self.help = help            # set after __init__: Click resets it


class DocumentedCommand(click.Command):
    def __init__(self, *args, examples=None, **kwargs):
        self.examples = examples or []
        super().__init__(*args, **kwargs)

    def format_arguments(self, ctx, formatter):
        rows = [(p.human_readable_name, getattr(p, "help", "") or "")
                for p in self.get_params(ctx) if isinstance(p, click.Argument)]
        if rows:
            with formatter.section("Arguments (required, in this order)"):
                formatter.write_dl(rows)

    def format_options(self, ctx, formatter):
        # Click >= 8.2 calls format_arguments() itself; older versions don't.
        if not _CLICK_CALLS_FORMAT_ARGUMENTS:
            self.format_arguments(ctx, formatter)
        super().format_options(ctx, formatter)

    def format_examples(self, ctx, formatter):
        if self.examples:
            with formatter.section("Examples"):
                for example in self.examples:
                    formatter.write_text(example)

    def format_epilog(self, ctx, formatter):
        self.format_examples(ctx, formatter)
        super().format_epilog(ctx, formatter)


class SeedVaultGroup(click.Group):
    """Lists every command with its usage line, description, arguments and options."""

    def list_commands(self, ctx):
        return list(self.commands)          # keep the order commands were added in

    def format_commands(self, ctx, formatter):
        commands = [(name, self.get_command(ctx, name)) for name in self.list_commands(ctx)]
        commands = [(n, c) for n, c in commands if c is not None and not c.hidden]
        if not commands:
            return
        with formatter.section("Commands"):
            for name, cmd in commands:
                sub_ctx = click.Context(cmd, info_name=name, parent=ctx)
                usage = " ".join(cmd.collect_usage_pieces(sub_ctx))
                formatter.write_text(click.style(f"{ctx.command_path} {name} {usage}".rstrip(), bold=True))
                with formatter.indentation():
                    if cmd.help:
                        formatter.write_text(cmd.help)
                    if isinstance(cmd, DocumentedCommand):
                        cmd.format_arguments(sub_ctx, formatter)
                    opts = [p.get_help_record(sub_ctx) for p in cmd.get_params(sub_ctx)
                            if isinstance(p, click.Option) and "--help" not in p.opts]
                    opts = [o for o in opts if o]
                    if opts:
                        with formatter.section("Options"):
                            formatter.write_dl(opts)
                formatter.write_paragraph()
            formatter.write_text(f"Run '{ctx.command_path} COMMAND --help' for examples.")


def _non_negative(ctx, param, value):
    if value is not None and value < 0:
        raise click.BadParameter("must be 0 or more")
    return value


# --------------------------------------------------------------------------
# Commands
# --------------------------------------------------------------------------
@click.group(cls=SeedVaultGroup, invoke_without_command=True, context_settings=CONTEXT_SETTINGS)
@click.option("-f", "--file", "file_path", metavar="CONFIG", type=click.Path(exists=True, dir_okay=False),
              help="Run a download straight from a config file (e.g. one saved from "
                   "'Run from Parameters') instead of opening the app.")
@click.version_option(package_name="seed-vault", prog_name="SEED Vault")
@click.pass_context
def cli(ctx, file_path):
    """SEED Vault: search, download and archive seismic data from FDSN servers.

    \b
      seed-vault                     open the desktop application
      seed-vault -f config.cfg       run a download from a config file
      seed-vault COMMAND [ARGS]...   run one of the commands below
    """
    if ctx.invoked_subcommand is None:
        if file_path:
            click.echo(f"Processing file: {file_path}")
            run_main(from_file=file_path)
        else:
            from seed_vault.qt.app import main as gui_main
            raise SystemExit(gui_main([sys.argv[0]]))


@cli.command(name="gui", cls=DocumentedCommand, context_settings=CONTEXT_SETTINGS,
             help="Open the desktop application (also what plain 'seed-vault' does).")
def run_gui():
    from seed_vault.qt.app import main as gui_main
    raise SystemExit(gui_main([sys.argv[0]]))


@cli.command(name="sync-db", cls=DocumentedCommand, context_settings=CONTEXT_SETTINGS,
             help="Scan an existing SDS archive and record which data it holds in the database, "
                  "so SEED Vault knows what is already available locally and doesn't download it again.",
             examples=[
                 "seed-vault sync-db /data/SDS /data/database.sqlite",
                 "seed-vault sync-db /data/SDS /data/database.sqlite --newer-than 2025-06-01 --cpu 8",
                 "seed-vault sync-db /data/SDS /data/database.sqlite -sp \"AU.*.*.?H?.D.2025.???\"",
             ])
@click.argument("sds_path", cls=HelpArgument, metavar="SDS_PATH", type=click.Path(exists=True, file_okay=False),
                help="Root folder of the SDS archive (the folder containing the year folders). Must exist.")
@click.argument("db_path", cls=HelpArgument, metavar="DB_PATH", type=click.Path(dir_okay=False),
                help="SQLite database file to update, e.g. /data/database.sqlite. "
                     "Created (with its tables) if it doesn't exist.")
@click.option("-sp", "--search-patterns", metavar="PATTERN", default="??.*.*.???.?.????.???", show_default=True,
              help="Comma-separated SDS file-name patterns to include (wildcards: * and ?). "
                   "The default matches every file in a standard SDS archive.")
@click.option("-nt", "--newer-than", metavar="YYYY-MM-DD", type=click.DateTime(formats=["%Y-%m-%d"]), default=None,
              help="Only scan files modified after this date; useful for quick incremental syncs.")
@click.option("-c", "--cpu", metavar="N", default=0, type=int, callback=_non_negative, show_default=True,
              help="Number of processes to use; 0 = all CPU cores.")
@click.option("-g", "--gap-tolerance", metavar="SECONDS", default=60, type=int, callback=_non_negative,
              show_default=True,
              help="Gaps up to this many seconds are treated as continuous data.")
def populate_db(sds_path, db_path, search_patterns, newer_than, cpu, gap_tolerance):
    search_patterns_list = [p.strip() for p in search_patterns.split(",") if p.strip()]

    populate_database_from_sds(
        sds_path=sds_path,
        db_path=db_path,
        search_patterns=search_patterns_list,
        newer_than=newer_than,
        num_processes=cpu,
        gap_tolerance=gap_tolerance,
    )


@cli.command(name="clean-db", cls=DocumentedCommand, context_settings=CONTEXT_SETTINGS,
             help="Tidy up a database: rebuild its indexes, reclaim unused space (VACUUM) "
                  "and refresh query statistics (ANALYZE). Doesn't delete any records.",
             examples=["seed-vault clean-db /data/database.sqlite"])
@click.argument("db_path", cls=HelpArgument, metavar="DB_PATH", type=click.Path(exists=True, dir_okay=False),
                help="SQLite database file to clean up. Must exist.")
def run_clean_db(db_path):
    clean_database(db_path)


@cli.command(name="web", cls=DocumentedCommand, context_settings=CONTEXT_SETTINGS,
             help="Run the legacy browser (Streamlit) interface. Needs the optional 'web' extra "
                  "(see 'seed-vault web --help').",
             examples=["pip install \"seed-vault[web]\"   # once", "seed-vault web"])
def run_web():
    import importlib.util
    import subprocess
    if importlib.util.find_spec("streamlit") is None:
        raise click.ClickException("The web interface needs the optional extra: pip install 'seed-vault[web]'")
    path_to_run = os.path.join(par_dir, "ui", "app.py")
    subprocess.run([sys.executable, "-m", "streamlit", "run", path_to_run, "--server.runOnSave=true"])


if __name__ == "__main__":
    cli()
