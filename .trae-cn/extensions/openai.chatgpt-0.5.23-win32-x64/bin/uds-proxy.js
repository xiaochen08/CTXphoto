#!/usr/bin/env node

/*
 * This is a standalone Node.js file so that it can be run directly by spawning
 * a new process in the VS Code extension host, using `process.execPath` as the
 * program to run.
 *
 * This script connects to a Unix Domain Socket (UDS) at the path provided as
 * a command-line argument. It pipes data from standard input (stdin) to the
 * socket and from the socket to standard output (stdout), enabling communication
 * through the UDS.
 */

import net from "node:net";

const [socketPath] = process.argv.slice(2);

if (!socketPath) {
  console.error("Usage: connect.js <socket-path>");
  process.exit(1);
}

if (process.argv.slice(2).length !== 1) {
  console.error("Expected exactly one argument: <socket-path>");
  process.exit(1);
}

const socket = net.createConnection(socketPath);

process.stdin.pipe(socket);
socket.pipe(process.stdout);

socket.on("error", (err) => {
  console.error("Socket error:", err);
  process.exitCode = 1;
});

process.stdin.on("error", (err) => {
  console.error("stdin error:", err);
  process.exitCode = 1;
});

process.stdout.on("error", (err) => {
  console.error("stdout error:", err);
  process.exitCode = 1;
});

socket.on("close", () => {
  process.exit();
});

process.stdin.on("end", () => {
  socket.end();
});
