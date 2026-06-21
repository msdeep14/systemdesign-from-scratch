#!/usr/bin/env python3
"""
Seed the PhotoZ database with realistic volume to expose query bottlenecks.

Creates:
  - 10,000 users with profiles
  - 200 communities with memberships
  - 100,000 photos
  - ~300,000 follow relationships
  - 400,000 likes
  - 200,000 comments
  - 100,000 notifications

For running the test with different parameters, update the constants defined below. Refer chapter04/README.md for details
on script execution and result analysis.
"""

import sys
import os
import random
import uuid
import time

PHOTOZ_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', '..', 'photoz')
sys.path.insert(0, PHOTOZ_DIR)
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'bses.settings')
os.environ.setdefault('POSTGRES_HOST', 'localhost')

import django
django.setup()

from django.contrib.auth.models import User
from django.contrib.auth.hashers import make_password
from users.models import UserProfile, Follow
from photos.models import Photo, Like, Comment
from communities.models import Community, CommunityMembership
from notifications.models import Notification

NUM_USERS = 10000
NUM_COMMUNITIES = 200
NUM_PHOTOS = 100000
NUM_LIKES = 400000
NUM_COMMENTS = 200000
NUM_NOTIFICATIONS = 100000

FIRST_NAMES = [
    'Alex', 'Jordan', 'Taylor', 'Morgan', 'Casey', 'Riley', 'Avery', 'Quinn',
    'Harper', 'Blake', 'Drew', 'Sage', 'Rowan', 'River', 'Phoenix', 'Skyler',
    'Cameron', 'Dakota', 'Emerson', 'Finley', 'Hayden', 'Jamie', 'Kendall',
    'Logan', 'Micah', 'Noel', 'Parker', 'Reese', 'Sawyer', 'Tatum',
]

LAST_NAMES = [
    'Smith', 'Johnson', 'Williams', 'Brown', 'Jones', 'Garcia', 'Miller',
    'Davis', 'Rodriguez', 'Martinez', 'Wilson', 'Anderson', 'Thomas', 'Jackson',
    'White', 'Harris', 'Martin', 'Thompson', 'Moore', 'Young',
]

CAPTIONS = [
    'Beautiful sunset!', 'Coffee time', 'Weekend vibes', 'Nature walk',
    'City lights', 'Throwback Thursday', 'No filter needed', 'Living my best life',
    'Grateful for moments like these', 'Adventure awaits', 'Golden hour',
    'Peaceful morning', 'Road trip memories', 'Simple pleasures', '',
    'Exploring new places', 'Chasing sunsets', 'Perfect day', 'Making memories',
    'Feeling blessed', 'Views for days', 'Wanderlust', 'Good vibes only',
]

COMMENT_TEXTS = [
    'Nice photo!', 'Love this!', 'Stunning!', 'Where is this?', 'So beautiful!',
    'Amazing shot!', 'Goals!', 'Wow!', 'Incredible', 'This is gorgeous',
    'Great capture', 'Looks amazing', 'Wish I was there', 'Love the colors',
    'Perfect timing', 'So cool!', 'Beautiful composition', 'Awesome!',
    'Need to visit this place', 'Absolutely stunning', 'What camera?',
]

COMMUNITY_NAMES = [
    'Street Photography', 'Nature Lovers', 'Urban Explorers', 'Food Photography',
    'Travel Diaries', 'Portrait Masters', 'Landscape Club', 'Night Photography',
    'Macro World', 'Black & White', 'Film Photography', 'Drone Shots',
    'Architecture', 'Wildlife', 'Vintage Vibes', 'Minimalism', 'Abstract Art',
    'Sunset Chasers', 'Ocean Views', 'Mountain Life', 'City Skylines',
    'Pet Photos', 'Sports Action', 'Fashion Shots', 'Concert Photography',
    'Astrophotography', 'Street Art', 'Reflections', 'Silhouettes', 'Textures',
    'Rainy Days', 'Snow Scenes', 'Autumn Colors', 'Spring Blooms', 'Summer Vibes',
    'Golden Hour Club', 'Blue Hour Crew', 'Light Painting', 'Long Exposure',
    'HDR Photography', 'Panoramas', 'Candid Moments', 'Self Portraits',
    'Couples Photography', 'Family Moments', 'Newborn Photography', 'Wedding Shots',
    'Event Photography', 'Product Photography', 'Creative Edits',
]


def timed(label):
    class Timer:
        def __enter__(self):
            self.start = time.time()
            print(f"  {label}...", end='', flush=True)
            return self
        def __exit__(self, *args):
            elapsed = time.time() - self.start
            print(f" done ({elapsed:.1f}s)")
    return Timer()


def check_existing_data():
    user_count = User.objects.count()
    if user_count > 10:
        print(f"\n  WARNING: Database already has {user_count} users.")
        print("  Run with --reset to clear and re-seed, or --force to add more data.\n")
        return True
    return False


def clear_data():
    with timed("Clearing existing data"):
        Comment.objects.all().delete()
        Like.objects.all().delete()
        Notification.objects.all().delete()
        Photo.objects.all().delete()
        Follow.objects.all().delete()
        CommunityMembership.objects.all().delete()
        Community.objects.all().delete()
        UserProfile.objects.all().delete()
        User.objects.filter(is_superuser=False).delete()


def seed_users():
    with timed(f"Creating {NUM_USERS} users + profiles"):
        hashed_pw = make_password('password123')

        users = []
        for i in range(NUM_USERS):
            first = random.choice(FIRST_NAMES)
            last = random.choice(LAST_NAMES)
            users.append(User(
                username=str(uuid.uuid4())[:30],
                password=hashed_pw,
                first_name=first,
                last_name=last,
            ))
        users = User.objects.bulk_create(users)

        profiles = []
        for i, user in enumerate(users):
            profiles.append(UserProfile(
                user=user,
                username_display=f"{user.first_name.lower()}_{user.last_name.lower()}_{i}",
                first_name=user.first_name,
                last_name=user.last_name,
            ))
        UserProfile.objects.bulk_create(profiles)

    return users


def seed_communities(users):
    with timed(f"Creating {NUM_COMMUNITIES} communities + memberships"):
        communities = []
        for i in range(NUM_COMMUNITIES):
            base_name = COMMUNITY_NAMES[i % len(COMMUNITY_NAMES)]
            suffix = f" {i // len(COMMUNITY_NAMES) + 1}" if i >= len(COMMUNITY_NAMES) else ""
            name = f"{base_name}{suffix}"
            communities.append(Community(
                name=name,
                description=f"A community for {name.lower()} enthusiasts.",
                creator=random.choice(users),
            ))
        communities = Community.objects.bulk_create(communities)

        memberships = []
        seen = set()
        for community in communities:
            # Creator membership
            key = (community.id, community.creator_id)
            if key not in seen:
                seen.add(key)
                memberships.append(CommunityMembership(
                    community=community,
                    user=community.creator,
                    role='creator',
                    status='accepted',
                ))

            # Random 10-30 additional members
            members = random.sample(users, random.randint(10, 30))
            for member in members:
                key = (community.id, member.id)
                if key not in seen:
                    seen.add(key)
                    memberships.append(CommunityMembership(
                        community=community,
                        user=member,
                        role='member',
                        status='accepted',
                    ))

        CommunityMembership.objects.bulk_create(memberships, ignore_conflicts=True)

    return communities


def seed_photos(users, communities):
    with timed(f"Creating {NUM_PHOTOS} photos"):
        photos = []
        for _ in range(NUM_PHOTOS):
            photo = Photo(
                user=random.choice(users),
                image='photos/seed/dummy.jpg',
                caption=random.choice(CAPTIONS),
            )
            # ~20% of photos belong to a community
            if random.random() < 0.2:
                photo.community = random.choice(communities)
            photos.append(photo)

        photos = Photo.objects.bulk_create(photos)

    # Spread created_at timestamps over the past 90 days
    with timed("Spreading photo timestamps over 90 days"):
        from django.db import connection
        with connection.cursor() as cursor:
            cursor.execute(
                "UPDATE photos_photo "
                "SET created_at = NOW() - MOD(id, 90) * INTERVAL '1 day'"
                "                       - MOD(id, 24) * INTERVAL '1 hour'"
                "                       - MOD(id, 60) * INTERVAL '1 minute'"
            )

    return photos


def seed_follows(users):
    with timed("Creating follow relationships (10-50 per user)"):
        follow_set = set()
        follows = []
        user_ids = [u.id for u in users]

        for user in users:
            num_to_follow = random.randint(10, 50)
            target_ids = random.sample(user_ids, num_to_follow + 1)
            target_ids = [tid for tid in target_ids if tid != user.id][:num_to_follow]
            for tid in target_ids:
                key = (user.id, tid)
                if key not in follow_set:
                    follow_set.add(key)
                    follows.append(Follow(follower_id=user.id, following_id=tid))

        Follow.objects.bulk_create(follows, batch_size=1000, ignore_conflicts=True)
        print(f"       {len(follows)} follow relationships created")


def seed_likes(users, photos):
    with timed(f"Creating {NUM_LIKES} likes"):
        like_set = set()
        likes = []
        user_ids = [u.id for u in users]
        photo_ids = [p.id for p in photos]

        attempts = 0
        while len(likes) < NUM_LIKES and attempts < NUM_LIKES * 3:
            attempts += 1
            uid = random.choice(user_ids)
            pid = random.choice(photo_ids)
            key = (uid, pid)
            if key not in like_set:
                like_set.add(key)
                likes.append(Like(user_id=uid, photo_id=pid))

        Like.objects.bulk_create(likes, batch_size=1000, ignore_conflicts=True)


def seed_comments(users, photos):
    with timed(f"Creating {NUM_COMMENTS} comments"):
        user_ids = [u.id for u in users]
        photo_ids = [p.id for p in photos]

        comments = []
        for _ in range(NUM_COMMENTS):
            comments.append(Comment(
                user_id=random.choice(user_ids),
                photo_id=random.choice(photo_ids),
                text=random.choice(COMMENT_TEXTS),
            ))

        Comment.objects.bulk_create(comments, batch_size=1000)


def seed_notifications(users, photos):
    with timed(f"Creating {NUM_NOTIFICATIONS} notifications"):
        user_ids = [u.id for u in users]
        photo_ids = [p.id for p in photos]
        types = ['photo_like', 'photo_comment']

        notifications = []
        for _ in range(NUM_NOTIFICATIONS):
            sender_id, recipient_id = random.sample(user_ids, 2)

            ntype = random.choice(types)
            notifications.append(Notification(
                recipient_id=recipient_id,
                sender_id=sender_id,
                type=ntype,
                message=f"Someone interacted with your photo.",
                photo_id=random.choice(photo_ids),
                is_read=random.random() < 0.4,  # 40% read
            ))

        Notification.objects.bulk_create(notifications, batch_size=1000)

def main():
    reset = '--reset' in sys.argv
    reset_only = '--reset-only' in sys.argv
    force = '--force' in sys.argv

    print("\n" + "=" * 60)
    print("  Photoz Database Seeder -- Chapter 04")
    print("=" * 60)

    if not reset and not reset_only and not force and check_existing_data():
        sys.exit(1)

    if reset or reset_only:
        clear_data()

    if reset_only:
        print("  Data cleared. Exiting due to --reset-only flag.")
        sys.exit(0)

    overall_start = time.time()

    users = seed_users()
    communities = seed_communities(users)
    photos = seed_photos(users, communities)
    seed_follows(users)
    seed_likes(users, photos)
    seed_comments(users, photos)
    seed_notifications(users, photos)

    elapsed = time.time() - overall_start

    print("\n" + "-" * 60)
    print(f"     Seeding complete in {elapsed:.1f}s")
    print(f"     Users:         {User.objects.filter(is_superuser=False).count()}")
    print(f"     Communities:   {Community.objects.count()}")
    print(f"     Photos:        {Photo.objects.count()}")
    print(f"     Follows:       {Follow.objects.count()}")
    print(f"     Likes:         {Like.objects.count()}")
    print(f"     Comments:      {Comment.objects.count()}")
    print(f"     Notifications: {Notification.objects.count()}")
    print("-" * 60 + "\n")


if __name__ == '__main__':
    main()
