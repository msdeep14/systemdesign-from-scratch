# Summary
Building a social media application where users upload the photos and share them with the followers. Here is the detailed list of features supported by application:

* Users create personal profile with details like username, first name, last name, profile picture and interests. Username and first name are mandatory inputs. The username is a unique identifier for each user. The system should check if the username already exists in the system. If it exists, then prompt the user to use try with some other username.
* Users can update already created profiles such as a profile photo and other details.
* Every user account is public and there is no separate privacy at user level. This feature is much similar to how Twitter/X operate.
* Users can follow or unfollow other users.
* Users can upload photos.
* Users can view their own personal profile including details like about section, all uploaded photos, followers and followee information. There is also an edit button in the personal profile to update any information. For now, the system restricts to not allow updating of username.
* Users should see photos in their newsfeed from other users they’re following.
* Users can react to the photos shown in their newsfeed with a like button or add a comment.
* Users can search for other people using username or name and further look up their profile.
* Users can delete their profile or a specific uploaded photo by them. This action is allowed by viewing their personal profile.
* A user can form a community on the applicaiton and add members to it. Once user form the community and member addition, the members (other users) are notified to join the community. It's upto them to accept or reject the invitation.
* The community members can upload photos which are visible to community members in their newsfeed. So essentially, the overall newsfeed is built out of two types of posts:
  1. Posts from users they follow.
  2. Posts from communities they are members of.

# UI/UX
* Web applicaiton should be very modern and premium looking.
* Color scheme and theme should be very soothing to the eyes.
* Should follow the mobile first approach. However, should be responsive for desktop view as well. This is first version of the application and we're just focusing on the web version of the application.

# Tech Stack 
- **Frontend Framework:** HTML/ CSS / Javascript as part of Python Django framework
- **Backend / API:** Python Django
- **Database:** PostgreSQL

The application is a Python Django monolithic web application with all these features built.

# Architecture
THe system can consist of below components to serve the different features:
- user component: user related actions
- photo component: photo related actions
- newsfeed component: construct newsfeed
- community component: community related actions

The APIs should be clean and follows REST principles.

# Code Standards
- Don't create random abstractions. Keep the code simple. Don't think too much in future scope. 
- Don't add features which are not required for the current version.
- Follow the django coding standards.
- Don't add unncessary comments. If the code is too complex, you can add comments to explain it. The idea should always be code and method names / class names / database schema should be self explanatory.
- Don't over-engineer. Do not abstract for the sake of abstraction. The logic should be straightforward and easy to follow.
- Don't make assumptions on your own. If you require clarification, ask me .
- If there are multiple ways of implementing a feature, choose the simplest one. The reasoning should be there, why specific implementation path is choosen. If the code can be written in 10 lines instead of 100, choose to write in 10 lines.
- Always ask if something is confusing.

