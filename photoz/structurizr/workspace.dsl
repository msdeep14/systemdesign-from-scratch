workspace "Photoz" "A photo-sharing social network" {

    model {
        user = person "User" "User of Photoz" "Person"

        photozSystem = softwareSystem "Photoz System" "Core Platform" {
            
            group "Load Balancer Node" {
                loadBalancer = container "Nginx Load Balancer" "Routes HTTP traffic" "Nginx"
                consul = container "Consul Server" "Service Discovery" "HashiCorp Consul"
            }
            
            group "App Node (Auto Scaling Group)" {
                webApp = container "App Servers" "Business Logic" "Python and Django" "WebApp" {
                    usersApp = component "Users App" "Accounts and Auth" "Django App"
                    photosApp = component "Photos App" "Photo Logic" "Django App"
                    communitiesApp = component "Communities App" "Community Logic" "Django App"
                    newsfeedApp = component "Newsfeed App" "Feed Logic" "Django App"
                    notificationsApp = component "Notifications App" "Notifications" "Django App"
                }
                kafkaConsumers = container "Kafka Consumers" "Event consumers" "Python Daemons" "Worker"
            }
            
            group "Kafka Cluster (KRaft)" {
                kafkaCluster = container "Kafka Cluster" "(KRaft)" "Apache Kafka" "Queue"
            }
            
            group "Database Node" {
                databasePrimary = container "Primary Database" "Core DB (Writes)" "PostgreSQL" "Database"
            }
            
            group "Database Replica Node" {
                databaseReplica = container "Read Replicas" "Core DB (Reads)" "PostgreSQL" "Database"
            }
            
            group "Redis Node" {
                cache = container "Redis Cache" "In-memory cache for newsfeeds, rate limits, and like sets" "Redis" "Cache"
            }
        }

        cdn = softwareSystem "CloudFront CDN" "Global CDN" "AWS CloudFront"
        s3 = softwareSystem "Amazon S3" "Object Storage" "AWS S3"

        # External Relationships
        user -> loadBalancer "Visits site"
        user -> cdn "Gets images"
        cdn -> s3 "Gets origin"
        
        # Container Relationships
        consul -> loadBalancer "Updates routing"
        webApp -> consul "Registers"
        loadBalancer -> webApp "Routes traffic"
        webApp -> databasePrimary "Writes"
        webApp -> databaseReplica "Reads"
        databasePrimary -> databaseReplica "Replicates"
        webApp -> cache "Caches/Reads"
        webApp -> s3 "Uploads"
        
        webApp -> kafkaCluster "Publishes events (likes, follows, uploads, notifications, deletions)"
        kafkaConsumers -> kafkaCluster "Consumes event batches"
        kafkaConsumers -> databasePrimary "Bulk writes & updates"
        kafkaConsumers -> cache "Invalidates & updates caches"

        # Component Relationships (High-Level Intent)
        usersApp -> databasePrimary "User Data"
        photosApp -> databasePrimary "Photo Data"
        communitiesApp -> databasePrimary "Community Data"
        newsfeedApp -> cache "Feeds"
        notificationsApp -> databasePrimary "Notifications"

        loadBalancer -> usersApp "Routes"
        loadBalancer -> photosApp "Routes"
        loadBalancer -> communitiesApp "Routes"
        loadBalancer -> newsfeedApp "Routes"
        
        photosApp -> s3 "Uploads"
        photosApp -> kafkaCluster "Publishes like and upload events"
        usersApp -> kafkaCluster "Publishes follow events"
        notificationsApp -> kafkaCluster "Publishes notification events"
        newsfeedApp -> kafkaCluster "Publishes deletion events"
    }

    views {
        systemContext photozSystem "SystemContext" {
            include *
            include cdn
            autoLayout
        }

        container photozSystem "Containers" {
            include *
            include cdn
            autoLayout
        }

        component webApp "Components" {
            include *
            autoLayout
        }

        styles {
            element "Element" {
                fontSize 32
                background #ffffff
                color #000000
                stroke #000000
            }
            element "Software System" {
                background #ffffff
                color #000000
                stroke #000000
            }
            element "Container" {
                background #ffffff
                color #000000
                stroke #000000
            }
            element "WebApp" {
                background #ffffff
                color #000000
                stroke #000000
            }
            element "Worker" {
                background #ffffff
                color #000000
                stroke #000000
            }
            element "Queue" {
                shape Pipe
                background #ffffff
                color #000000
                stroke #000000
            }
            element "Database" {
                shape Cylinder
                background #ffffff
                color #000000
                stroke #000000
            }
            element "Cache" {
                shape Cylinder
                background #ffffff
                color #000000
                stroke #000000
            }
            element "Person" {
                shape Person
                background #ffffff
                color #000000
                stroke #000000
            }
            relationship "Relationship" {
                fontSize 40
                thickness 3
                color #000000
            }
        }
    }
}
