---
architecture: ../../photoz.calm.json
id: index
title: Welcome to CALM Documentation
sidebar_position: 1
slug: /
---

# Welcome to CALM Documentation

This documentation is generated from the **CALM Architecture-as-Code** model.

## High Level Architecture
```mermaid
---
config:
  theme: base
  themeVariables:
    fontFamily: -apple-system, BlinkMacSystemFont, 'Segoe WPC', 'Segoe UI', system-ui, 'Ubuntu', sans-serif
    darkMode: false
    fontSize: 14px
    edgeLabelBackground: '#d5d7e1'
    lineColor: '#000000'
---
%%{init: {"layout": "elk", "flowchart": {"htmlLabels": false}}}%%
flowchart TB
classDef boundary fill:#ffffff,stroke:#000000,stroke-dasharray: 5 4,stroke-width:1px,color:#000000;
classDef node fill:#ffffff,stroke:#000000,stroke-width:1px,color:#000000;
classDef iface fill:#ffffff,stroke:#000000,stroke-width:1px,font-size:10px,color:#000000;
classDef highlight fill:#ffffff,stroke:#000000,stroke-width:1px,color:#000000;


    s3["Amazon S3"]:::node
    kafka-cluster["Kafka Cluster (KRaft)"]:::node
    kafka-consumers["Kafka Consumer Daemons"]:::node
    cdn["CloudFront CDN"]:::node
    web-app["Django App Servers"]:::node
    load-balancer["Nginx Load Balancer"]:::node
    node_end-user["Photoz User"]:::node
    primary-db["Primary PostgreSQL Database"]:::node
    replica-db["Read Replica PostgreSQL Database"]:::node
    cache["Redis Cache"]:::node

    load-balancer -->|Routes dynamic traffic to| web-app
    web-app -->|Reads from and writes to| primary-db
    web-app -->|Reads from| replica-db
    primary-db -->|Replicates data to| replica-db
    web-app -->|Reads from and writes to| cache
    web-app -->|Uploads photos| s3
    cdn -->|Fetches images from origin| s3
    node_end-user -->|Browses the site, manages profile, and uploads photos| load-balancer
    node_end-user -->|Downloads and views photos| cdn
    web-app -->|Publishes asynchronous events to| kafka-cluster
    kafka-consumers -->|Consumes event batches from| kafka-cluster
    kafka-consumers -->|Bulk writes and updates| primary-db
    kafka-consumers -->|Updates and invalidates cache keys in| cache



```

## Nodes
- [Photoz User](nodes/end-user)
- [Nginx Load Balancer](nodes/load-balancer)
- [Django App Servers](nodes/web-app)
- [Primary PostgreSQL Database](nodes/primary-db)
- [Read Replica PostgreSQL Database](nodes/replica-db)
- [Redis Cache](nodes/cache)
- [CloudFront CDN](nodes/cdn)
- [Amazon S3](nodes/s3)
- [Kafka Cluster (KRaft)](nodes/kafka-cluster)
- [Kafka Consumer Daemons](nodes/kafka-consumers)

## Relationships
- [Lb To Webapp](relationships/lb-to-webapp)
- [Webapp To Primarydb](relationships/webapp-to-primarydb)
- [Webapp To Replicadb](relationships/webapp-to-replicadb)
- [Primarydb To Replicadb](relationships/primarydb-to-replicadb)
- [Webapp To Cache](relationships/webapp-to-cache)
- [Webapp To S3](relationships/webapp-to-s3)
- [Cdn To S3](relationships/cdn-to-s3)
- [User To Lb](relationships/user-to-lb)
- [User To Cdn](relationships/user-to-cdn)
- [Webapp To Kafka](relationships/webapp-to-kafka)
- [Consumers To Kafka](relationships/consumers-to-kafka)
- [Consumers To Primarydb](relationships/consumers-to-primarydb)
- [Consumers To Cache](relationships/consumers-to-cache)

## Flows
_No flows defined._

## Metadata
<p class="empty-message">No metadata defined.</p>

## ADRs
_No ADRs defined._
