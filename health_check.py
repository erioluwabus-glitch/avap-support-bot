import os
from http.server import BaseHTTPRequestHandler, HTTPServer

class HealthCheckHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path == "/health":
            # Respond with 200 OK and a simple JSON
            self.send_response(200)
            self.send_header("Content-type", "application/json")
            self.end_headers()
            self.wfile.write(b'{"status": "ok"}')  # Simple health check response

def run_health_check_server(port=80):
    server_address = ('', port)  # Listen on port 80 for the health check
    httpd = HTTPServer(server_address, HealthCheckHandler)
    print(f"Health check server running on port {port}...")
    httpd.serve_forever()

if __name__ == "__main__":
    run_health_check_server()  # This will run the server when executed directly
