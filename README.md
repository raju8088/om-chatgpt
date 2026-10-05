# OmniDimension Control Center

A local browser interface for the OmniDimension API.

## Run

```powershell
py -3 server.py --port 8787
```

Then open:

```text
http://127.0.0.1:8787
```

## What it includes

- A private backend proxy for OmniDimension API calls.
- A SQLite database at `data/omnidim_ui.sqlite3`.
- Local API key storage, request history, and saved payloads.
- Endpoint screens in this sequence: Sessions, Agents, Calls, Bulk Calls, Knowledge Base, Phone Numbers, Providers, Simulation, Reseller/Admin.
- Protected confirmation on actions that can place calls, create cost, delete data, change credits, or alter live campaigns.

## Notes

- The browser never receives the API key. The backend adds it to outgoing OmniDimension requests.
- Base URL defaults to `https://omnidim.io/api/v1`.
- PDF knowledge-base uploads are handled by the UI helper, which converts the selected PDF into the Base64 body expected by the API.
