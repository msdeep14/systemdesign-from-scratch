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
                celeryWorker = container "Celery Worker" "Background tasks" "Celery" "Worker"
            }
            
            group "Database Node" {
                databasePrimary = container "Primary Database" "Core DB (Writes)" "PostgreSQL" "Database"
            }
            
            group "Database Replica Node" {
                databaseReplica = container "Read Replicas" "Core DB (Reads)" "PostgreSQL" "Database"
            }
            
            group "Redis Node" {
                cache = container "Cache and Message Broker" "Cache and Queue" "Redis" "Cache"
                celeryBeat = container "Celery Beat" "Task Scheduler" "Celery" "Worker"
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
        
        celeryBeat -> cache "Pushes tasks"
        celeryWorker -> cache "Pulls tasks"
        celeryWorker -> databasePrimary "Bulk writes"
        webApp -> cache "Pushes tasks"

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
            element "Software System" {
                background #1168bd
                color #ffffff
            }
            element "Container" {
                background #438dd5
                color #ffffff
            }
            element "WebApp" {
                background #205c40
                color #ffffff
            }
            element "Worker" {
                background #4a9c6d
                color #ffffff
            }
            element "Database" {
                shape Cylinder
                background #b03a2e
                color #ffffff
            }
            element "Cache" {
                shape Cylinder
                background #d35400
                color #ffffff
            }
            element "Person" {
                shape Person
                background #08427b
                color #ffffff
            }
            relationship "Relationship" {
                fontSize 40
                thickness 3
                color #000000
            }
        }
    }
}
