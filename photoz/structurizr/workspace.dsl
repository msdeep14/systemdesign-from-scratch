workspace "Photoz" "A photo-sharing social network" {

    model {
        user = person "User" "A user of the Photoz application."

        photozSystem = softwareSystem "Photoz System" "Allows users to upload photos, join communities, and view their newsfeed." {
            
            group "Load Balancer Node" {
                loadBalancer = container "Nginx Load Balancer" "Routes incoming traffic to available app servers and serves static assets." "Nginx"
                consul = container "Consul Server" "Service discovery and health checking to assist with autoscaling." "HashiCorp Consul"
            }
            
            webApp = container "App Servers" "Horizontally scalable application servers handling business logic." "Python and Django" {
                usersApp = component "Users App" "Manages user accounts, profiles, and authentication." "Django App"
                photosApp = component "Photos App" "Manages photo uploads, processing, and metadata." "Django App"
                communitiesApp = component "Communities App" "Manages communities, memberships, and posts." "Django App"
                newsfeedApp = component "Newsfeed App" "Aggregates posts for the user's feed." "Django App"
                notificationsApp = component "Notifications App" "Manages and delivers notifications." "Django App"
            }
            
            databasePrimary = container "Primary Database" "Stores user profiles, photos metadata, communities, and relationships (Writes)." "PostgreSQL" "Database"
            
            databaseReplica = container "Read Replicas" "Read-only database replicas for scaling read queries." "PostgreSQL" "Database"
            
            cache = container "Cache" "Caches newsfeeds and frequently accessed data." "Redis" "Database"
        }

        cdn = softwareSystem "CloudFront CDN" "Caches and serves uploaded images globally." "AWS CloudFront"
        s3 = softwareSystem "Amazon S3" "Object storage for uploaded photos (CDN Origin)." "AWS S3"

        # External Relationships
        user -> loadBalancer "Visits photoz.com for HTML/JSON and static assets"
        user -> cdn "Fetches images"
        cdn -> s3 "Fetches images from origin"
        
        # Container Relationships
        consul -> loadBalancer "Updates routing config with healthy nodes"
        webApp -> consul "Registers service and reports health"
        loadBalancer -> webApp "Routes dynamic traffic to"
        webApp -> databasePrimary "Writes to"
        webApp -> databaseReplica "Reads from"
        databasePrimary -> databaseReplica "Replicates data to"
        webApp -> cache "Reads from and writes to"
        webApp -> s3 "Uploads photos"

        # Component Relationships (High-Level Intent)
        usersApp -> databasePrimary "Reads/Writes User Data"
        photosApp -> databasePrimary "Reads/Writes Photo Data"
        communitiesApp -> databasePrimary "Reads/Writes Community Data"
        newsfeedApp -> cache "Caches and retrieves feeds"
        notificationsApp -> databasePrimary "Reads/Writes Notification Data"

        loadBalancer -> usersApp "Routes traffic"
        loadBalancer -> photosApp "Routes traffic"
        loadBalancer -> communitiesApp "Routes traffic"
        loadBalancer -> newsfeedApp "Routes traffic"
        
        photosApp -> s3 "Uploads photos via"
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
            }
            
        }
    }
}
