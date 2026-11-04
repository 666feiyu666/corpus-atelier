#!/usr/bin/env node
/**
 * Refuse to start an interface server on a port that is already taken.
 *
 * Nuxt would otherwise move to the next free port on its own. The browser would
 * then load an interface whose numbers no longer mean what the documents say,
 * and a request could land on another local project's server. Failing here keeps
 * the fixed ports in `package.json` honest: the port either belongs to this
 * interface or the command stops.
 */
import net from 'node:net'

const port = Number(process.argv[2])
if (!Number.isInteger(port) || port < 1 || port > 65535) {
  console.error('require-port: pass the port to check, e.g. `node scripts/require-port.mjs 3211`.')
  process.exit(2)
}

/** Whether something already accepts connections on the port. */
function listening() {
  return new Promise((resolve) => {
    const socket = net.connect({ port, host: '127.0.0.1' })
    const done = (answer) => {
      socket.destroy()
      resolve(answer)
    }
    socket.setTimeout(300, () => done(false))
    socket.once('connect', () => done(true))
    socket.once('error', () => done(false))
  })
}

/** Whether this process could bind the port at all. */
function bindable() {
  return new Promise((resolve) => {
    const server = net.createServer()
    server.once('error', () => resolve(false))
    server.listen({ port }, () => server.close(() => resolve(true)))
  })
}

if ((await listening()) || !(await bindable())) {
  const hint = process.platform === 'win32'
    ? `netstat -ano | findstr :${port}`
    : `lsof -nP -iTCP:${port} -sTCP:LISTEN`
  console.error(
    `Port ${port} is already in use, so the interface will not start on it.\n`
    + 'This project never takes over a port another program is using and never moves to a '
    + `different one by itself: either would point the browser at someone else's server.\n`
    + `Stop the process holding it (${hint}), or change the port here, in package.json, `
    + 'and in nuxt.config.ts together.',
  )
  process.exit(1)
}
