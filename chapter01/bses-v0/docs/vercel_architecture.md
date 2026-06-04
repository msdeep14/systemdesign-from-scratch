# Vercel Deployment Architecture

This diagram illustrates the architecture of the BSES v0 application when deployed on Vercel's serverless infrastructure, contrasting with the traditional Docker/EC2 monolith.

```mermaid
flowchart TD
    %% Define Styles
    classDef user fill:#e2e8f0,stroke:#64748b,stroke-width:2px,color:#0f172a
    classDef vercel fill:#000000,stroke:#a1a1aa,stroke-width:2px,color:#ffffff
    classDef aws fill:#ff9900,stroke:#d97706,stroke-width:2px,color:#ffffff
    classDef db fill:#336791,stroke:#0284c7,stroke-width:2px,color:#ffffff
    
    %% Nodes
    Client["User (Browser/Mobile)"]:::user
    
    subgraph Vercel ["Vercel Infrastructure"]
        Edge["Vercel Edge Network\n(CDN & Routing)"]:::vercel
        Static["Vercel Static Hosting\n(HTML, CSS, JS)"]:::vercel
        Serverless["Vercel Serverless Functions\n(Python/Django WSGI)"]:::vercel
    end
    
    subgraph External ["External Services"]
        Postgres[(Remote PostgreSQL\nNeon / Supabase / RDS)]:::db
        S3[("AWS S3 Bucket\n(Media/Photos)")]:::aws
    end

    %% Connections
    Client -->|HTTPS| Edge
    Edge -->|/static/* routes| Static
    Edge -->|/* dynamic routes| Serverless
    
    Serverless -->|Read/Write queries\n(psycopg2)| Postgres
    Serverless -->|Uploads & Signed URLs\n(boto3)| S3
    
    Client -.->|Direct Image Fetching| S3
```

### Key Architectural Shifts

1. **Serverless Execution:** Instead of a long-running Gunicorn server, Django runs inside ephemeral Vercel Serverless Functions. They spin up on demand to process dynamic HTTP requests and shut down when idle.
2. **Decoupled Database:** Vercel does not host databases natively. The PostgreSQL database must be hosted on an external managed provider (e.g., Neon, Supabase, or AWS RDS).
3. **Decoupled Media Storage:** Vercel's filesystem is read-only. User-uploaded files (like profile pictures and community photos) are offloaded directly to an external AWS S3 Bucket via `django-storages`.
4. **Edge Caching:** Static assets are served globally via Vercel's Edge Network CDN rather than passing through WhiteNoise inside the Python app.
