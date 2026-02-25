# Copyright (c) 2022-2024 anabrid GmbH
# Contact: https://www.anabrid.com/licensing/
# SPDX-License-Identifier: MIT OR GPL-2.0-or-later

import logging
import sys
import typing
from pathlib import Path

import asyncclick as click
from asyncclick.parser import split_arg_string
from prompt_toolkit import PromptSession
from prompt_toolkit.completion import CompleteEvent, Completer, Completion
from prompt_toolkit.document import Document
from prompt_toolkit.history import FileHistory, History
from prompt_toolkit.patch_stdout import StdoutProxy

from pybrid.base.utils.logging import redirect_logger_stream_handlers

logger = logging.getLogger(__name__)


class ShellCompleter(Completer):
    base_group: click.Group
    base_ctx: click.Context

    def __init__(self, base_group: click.Group, base_ctx: click.Context) -> None:
        self.base_group = base_group
        self.base_ctx = base_ctx

    def get_completions(self, document: Document, complete_event: CompleteEvent) -> typing.Iterable[Completion]:
        raise NotImplementedError

    async def get_completions_async(self, document: Document, complete_event: CompleteEvent) -> typing.AsyncGenerator[
        Completion, None]:

        # Split input string into parts
        subcmd_args = click.parser.split_arg_string(document.text)
        # If current command line is empty or ends with a space, we add an empty additional argument
        if not document.text or document.text.endswith(" "):
            subcmd_args.append("")

        # If there is no or only one word, we are completing the name of a subcommand
        if len(subcmd_args) == 1:
            start_position = -len(subcmd_args[0]) if subcmd_args else 0
            for cmd_name in self.base_group.list_commands(self.base_ctx):
                if cmd_name.startswith(subcmd_args[0]):
                    yield Completion(text=cmd_name, start_position=start_position)
            return

        # Otherwise, we are completing arguments of a subcommand, which we need to find first
        try:
            subcmd_name, subcmd, subcmd_args = await self.base_group.resolve_command(self.base_ctx, subcmd_args)
        except click.exceptions.UsageError:
            # No such command
            return

        # Find subcmd parameter corresponding to current cursor position and basically return its shell_complete
        try:
            async with await subcmd.make_context(subcmd_name, subcmd_args[:-1], parent=self.base_ctx,
                                                 resilient_parsing=True) as subctx:
                param_to_complete, incomplete = click.shell_completion._resolve_incomplete(subctx, [], subcmd_args[-1])
                for completion in param_to_complete.shell_complete(subctx, incomplete):
                    yield Completion(text=completion.value, start_position=-len(incomplete), display=completion.value,
                                     display_meta=completion.help)
        except:
            return


class Shell:
    base_group: click.Group
    base_ctx: click.Context

    completer: Completer
    history: typing.Optional[History]
    session: PromptSession

    slug: str
    prompt: str

    def __init__(self, base_group: click.Group, base_ctx: click.Context, slug="shell", prompt=">> ",
                 completer_class=None) -> None:
        if completer_class is None:
            completer_class = ShellCompleter

        self.base_group = base_group
        self.base_ctx = base_ctx
        self.completer = completer_class(base_group, base_ctx)
        self.history = self._create_history(slug)
        self.session = PromptSession(history=self.history, completer=self.completer)
        self.stdout_proxy = StdoutProxy(sleep_between_writes=0.25)

        self.slug = slug
        self.prompt = prompt

        self._register_additional_commands()

    def _register_additional_commands(self):
        @self.base_group.command()
        def exit():
            raise click.exceptions.Exit

    def _create_history(self, slug: str) -> typing.Optional[History]:
        try:
            xdg_data_dir = Path.home() / ".local" / "share"
            xdg_data_dir.mkdir(exist_ok=True)
            history_filename = f"pybrid-shell-history-{slug}"
            return FileHistory(str(xdg_data_dir / history_filename))
        except Exception as exc:
            logger.warning("Error while creating history for shell: %s. Continuing without history.", exc)
            return None

    async def execute_cmdline(self, cmd_str):
        logger.debug("Executing '%s'.", cmd_str)
        # Split input string into parts
        subcmd_args = split_arg_string(cmd_str)
        # Resolve subcommand, which may throw several exceptions
        try:
            subcmd_name, subcmd, subcmd_args = await self.base_group.resolve_command(self.base_ctx, subcmd_args)
        except click.exceptions.Exit:
            # resolve_command throws Exit e.g. when "?" is entered.
            return
        except click.exceptions.UsageError as exc:
            # Unknown command
            click.echo(exc)
            click.echo("Available commands: " + ", ".join(self.base_group.list_commands(self.base_ctx)))
            return

        # Simulate calling the command by creating a context and invoking the command.
        async with await subcmd.make_context(subcmd_name, subcmd_args, parent=self.base_ctx) as subctx:
            await subcmd.invoke(subctx)

    async def repl_loop(self):
        while True:
            # Ask for input
            cmd_str = await self.session.prompt_async(self.prompt)
            if not cmd_str:
                click.echo("Type '?' for help.")
                click.echo("Available commands: " + ", ".join(self.base_group.list_commands(self.base_ctx)))
                continue
            # Execute input
            try:
                await self.execute_cmdline(cmd_str)
            except click.exceptions.Exit:
                break
            except Exception as exc:
                # Do not actually fail in an interactive repl loop, just log it
                logger.exception("Error while executing '%s': %s", cmd_str, exc)

    def __enter__(self):
        redirect_logger_stream_handlers(from_=sys.stderr, to=self.stdout_proxy)
        self.stdout_proxy.__enter__()

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.stdout_proxy.__exit__(exc_type, exc_val, exc_tb)

