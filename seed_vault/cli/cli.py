import click
import os
from seed_vault.service.seismoloader import run_main, populate_database_from_sds
from seed_vault.analytics import init_telemetry
from seed_vault.models.config import SeismoLoaderSettings

dirname = os.path.dirname(__file__)
par_dir = os.path.dirname(dirname)

@click.group(invoke_without_command=True)
@click.option("-f", "--file", "file_path", type=click.Path(exists=True), required=False, help="Path to the config.cfg file.")
@click.pass_context
def cli(ctx, file_path):
    """Seed Vault CLI: A tool for seismic data processing."""
    
    # Initialize telemetry and track app open event
    try:
        # Try to load settings from file if provided, otherwise use defaults
        if file_path:
            settings = SeismoLoaderSettings.from_cfg_file(file_path)
        else:
            # Create minimal settings with defaults for telemetry
            settings = SeismoLoaderSettings()
        
        db_path = settings.db_path if settings.db_path else "SVdata/database.sqlite"
        telemetry = init_telemetry(settings, db_path)
        
        # Track app open event
        telemetry.track_event("app_open")
    except Exception as e:
        # Don't fail CLI execution if telemetry fails
        if os.getenv("DEBUG_TELEMETRY"):
            print(f"[Telemetry] Failed to track app_open: {e}")
    
    if ctx.invoked_subcommand is None:
        if file_path:
            click.echo(f"Processing file: {file_path}")
            run_main(from_file=file_path)
        else:
            path_to_run = os.path.join(par_dir, "ui", "app.py")
            os.system(f"streamlit run {path_to_run} --server.runOnSave=true")


@click.command(name="sync-db", help="Syncs the database with the local SDS repository.")
@click.argument("sds_path", type=click.Path(exists=True))
@click.argument("db_path", type=click.Path())
@click.option("-sp", "--search-patterns", default="??.*.*.???.?.????.???", help="Comma-separated list of search patterns.")
@click.option("-nt", "--newer-than", type=click.DateTime(formats=["%Y-%m-%d"]), default=None, help="Filter for files newer than a specific date (YYYY-MM-DD).")
@click.option("-c", "--cpu", default=0, type=int, help="Number of processes to use, input 0 to maximize.")
@click.option("-g", "--gap-tolerance", default=60, type=int, help="Gap tolerance in seconds.")
def populate_db(sds_path, db_path, search_patterns, newer_than, cpu, gap_tolerance):
    """Populates the database from the SDS path into the specified database file."""
    search_patterns_list = search_patterns.strip().split(",")

    populate_database_from_sds(
        sds_path=sds_path,
        db_path=db_path,
        search_patterns=search_patterns_list,
        newer_than=newer_than,
        num_processes=cpu,
        gap_tolerance=gap_tolerance,
    )



cli.add_command(populate_db, name="sync-db")


if __name__ == "__main__":
    cli()
