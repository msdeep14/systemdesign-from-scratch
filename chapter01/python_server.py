"""
python_server.py — A Bare-Bones HTTP Server Built From Raw Sockets

This script strips away all frameworks (Django, Flask, etc.) and shows
exactly what happens when you type http://localhost:9000 in your browser.

The journey:
  1. Create a socket          → like picking up a phone
  2. Bind to an address:port  → like assigning a phone number
  3. Listen                   → like turning the ringer on
  4. Accept                   → like picking up when someone calls (TCP 3-way handshake happens here)
  5. Receive the HTTP request → reading the raw bytes the browser sent
  6. Send an HTTP response    → writing raw bytes back to the browser
  7. Close the connection     → hanging up the phone

Run this script:
    python3 chapter01/python_server.py

Then open your browser and go to:
    http://localhost:9000

Watch the terminal output to see each step as it happens.
"""

import socket


# ──────────────────────────────────────────────────────────────────────
# STEP 1: Create a socket
# ──────────────────────────────────────────────────────────────────────
# AF_INET    = use IPv4 addresses (like 127.0.0.1)
# SOCK_STREAM = use TCP (reliable, ordered delivery — as opposed to UDP)
#
# At this point, the socket exists in memory but is not connected to
# anything. It's like a brand-new phone with no number assigned yet.
# ──────────────────────────────────────────────────────────────────────

server_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
print("[Step 1] Socket created (AF_INET + SOCK_STREAM = IPv4 TCP)")


# ──────────────────────────────────────────────────────────────────────
# STEP 2: Bind the socket to an address and port
# ──────────────────────────────────────────────────────────────────────
# bind() tells the OS: "When packets arrive for 127.0.0.1 on port 9000,
# deliver them to THIS socket."
#
# SO_REUSEADDR lets us restart the server immediately after stopping it,
# without waiting for the OS to release the port (otherwise you'd get
# "Address already in use" errors for ~60 seconds).
# ──────────────────────────────────────────────────────────────────────

server_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)

HOST = "127.0.0.1"
PORT = 9000
server_socket.bind((HOST, PORT))
print(f"[Step 2] Socket bound to {HOST}:{PORT}")


# ──────────────────────────────────────────────────────────────────────
# STEP 3: Listen for incoming connections
# ──────────────────────────────────────────────────────────────────────
# listen(backlog) tells the OS: "This socket is now a SERVER socket.
# Queue up to `backlog` pending connections while I'm busy handling one."
#
# After this call, the OS will respond to incoming TCP SYN packets with
# SYN-ACK on our behalf (the first two steps of the 3-way handshake),
# even before our code calls accept().
# ──────────────────────────────────────────────────────────────────────

BACKLOG = 5
server_socket.listen(BACKLOG)
print(f"[Step 3] Listening with backlog={BACKLOG}")
print(f"\n{'='*60}")
print(f"  Server is running at http://{HOST}:{PORT}")
print(f"  Open this URL in your browser. Press Ctrl+C to stop.")
print(f"{'='*60}\n")


# ──────────────────────────────────────────────────────────────────────
# STEP 4-7: The main loop — accept, read, respond, close
# ──────────────────────────────────────────────────────────────────────

request_count = 0

while True:
    try:
        # ──────────────────────────────────────────────────────────────
        # STEP 4: Accept a connection
        # ──────────────────────────────────────────────────────────────
        # accept() BLOCKS here — it waits until a client (browser)
        # connects. When a connection arrives:
        #   - The TCP 3-way handshake completes (SYN → SYN-ACK → ACK)
        #   - The OS creates a BRAND NEW socket just for this client
        #   - accept() returns that new socket + the client's address
        #
        # The original server_socket keeps listening for MORE connections.
        # Each client gets its own dedicated socket.
        # ──────────────────────────────────────────────────────────────

        print("Waiting for a connection...")
        client_socket, client_address = server_socket.accept()

        request_count += 1
        print(f"\n{'─'*60}")
        print(f"[Step 4] Request #{request_count}")
        print(f"  Connection accepted from {client_address[0]}:{client_address[1]}")
        print(f"  TCP 3-way handshake completed ✓")
        print(f"  New client socket created (fd={client_socket.fileno()})")

        # ──────────────────────────────────────────────────────────────
        # STEP 5: Receive the HTTP request
        # ──────────────────────────────────────────────────────────────
        # The browser sends raw bytes over the TCP connection.
        # A typical HTTP request looks like:
        #
        #   GET / HTTP/1.1\r\n
        #   Host: localhost:9000\r\n
        #   User-Agent: Mozilla/5.0 ...\r\n
        #   Accept: text/html\r\n
        #   \r\n
        #
        # recv(4096) reads up to 4096 bytes from the socket buffer.
        # ──────────────────────────────────────────────────────────────

        raw_request = client_socket.recv(4096)
        request_text = raw_request.decode("utf-8", errors="replace")

        # Parse just the first line to extract the method and path
        first_line = request_text.split("\r\n")[0] if request_text else "(empty)"
        parts = first_line.split(" ")
        method = parts[0] if len(parts) > 0 else "?"
        path = parts[1] if len(parts) > 1 else "?"

        print(f"\n[Step 5] Received HTTP request:")
        print(f"  Method: {method}")
        print(f"  Path:   {path}")
        print(f"  Raw first line: {first_line}")

        # Show all headers the browser sent
        headers = request_text.split("\r\n")[1:]
        print(f"  Headers received:")
        for header in headers:
            if header.strip():
                print(f"    {header}")

        # ──────────────────────────────────────────────────────────────
        # STEP 6: Send an HTTP response
        # ──────────────────────────────────────────────────────────────
        # We must write a valid HTTP response. The format is:
        #
        #   HTTP/1.1 200 OK\r\n          ← status line
        #   Content-Type: text/html\r\n  ← headers
        #   \r\n                          ← blank line = end of headers
        #   <html>...</html>              ← body
        #
        # The browser reads this, parses the HTML, and renders the page.
        # ──────────────────────────────────────────────────────────────

        html_body = f"""<!DOCTYPE html>
<html>
<head>
    <title>Raw Socket Server</title>
    <style>
        body {{
            font-family: 'Segoe UI', system-ui, sans-serif;
            max-width: 700px;
            margin: 60px auto;
            padding: 0 20px;
            background: #0f172a;
            color: #e2e8f0;
        }}
        h1 {{
            color: #38bdf8;
        }}
        .card {{
            background: #1e293b;
            border: 1px solid #334155;
            border-radius: 12px;
            padding: 24px;
            margin: 20px 0;
        }}
        code {{
            background: #334155;
            padding: 2px 6px;
            border-radius: 4px;
            font-size: 0.9em;
        }}
        .step {{
            color: #94a3b8;
            font-size: 0.85em;
            margin-bottom: 4px;
        }}
        .highlight {{
            color: #4ade80;
            font-weight: bold;
        }}
    </style>
</head>
<body>
    <h1>It works! 🎉</h1>
    <p>This page was served by a <span class="highlight">raw TCP socket</span> — no framework involved.</p>

    <div class="card">
        <div class="step">What just happened:</div>
        <ol>
            <li><code>socket()</code> — Created a TCP socket</li>
            <li><code>bind('{HOST}', {PORT})</code> — Claimed port {PORT}</li>
            <li><code>listen({BACKLOG})</code> — Started listening</li>
            <li><code>accept()</code> — Accepted your connection (TCP handshake ✓)</li>
            <li><code>recv()</code> — Read your browser's HTTP request</li>
            <li><code>sendall()</code> — Sent this HTML back to you</li>
            <li><code>close()</code> — Connection closed</li>
        </ol>
    </div>

    <div class="card">
        <div class="step">Your browser sent this request:</div>
        <p><code>{method} {path} HTTP/1.1</code></p>
        <p>From: <code>{client_address[0]}:{client_address[1]}</code></p>
        <p>This is request <span class="highlight">#{request_count}</span> since the server started.</p>
    </div>

    <div class="card">
        <div class="step">Key insight</div>
        <p>Django, Flask, Express — they all do exactly this under the hood.
        They just add layers on top: URL routing, template rendering,
        middleware, etc. But at the bottom, it's always
        <code>socket → bind → listen → accept → recv → send → close</code>.</p>
    </div>
</body>
</html>"""

        response = (
            "HTTP/1.1 200 OK\r\n"
            "Content-Type: text/html; charset=utf-8\r\n"
            f"Content-Length: {len(html_body.encode('utf-8'))}\r\n"
            "Connection: close\r\n"
            "\r\n"
            + html_body
        )

        client_socket.sendall(response.encode("utf-8"))
        print(f"\n[Step 6] HTTP response sent ({len(html_body)} bytes of HTML)")

        # ──────────────────────────────────────────────────────────────
        # STEP 7: Close the client connection
        # ──────────────────────────────────────────────────────────────
        # shutdown(SHUT_WR) tells the client: "I'm done sending data."
        # close() releases the socket resources.
        # The server_socket stays open and loops back to accept().
        # ──────────────────────────────────────────────────────────────

        client_socket.shutdown(socket.SHUT_WR)
        client_socket.close()
        print(f"[Step 7] Connection closed")
        print(f"{'─'*60}\n")

    except KeyboardInterrupt:
        print("\n\nShutting down server...")
        server_socket.close()
        print("Server socket closed. Goodbye!")
        break
