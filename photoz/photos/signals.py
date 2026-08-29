from django.dispatch import Signal

# Sent when a new photo is uploaded
# args: sender (Photo), photo (Photo instance)
photo_uploaded = Signal()

# Sent when a photo is deleted
# args: sender (Photo), user (User instance)
photo_deleted = Signal()

# Sent when a photo is liked
# args: sender (Photo), photo (Photo instance), liker (User instance)
photo_liked = Signal()

# Sent when a photo receives a comment
# args: sender (Photo), photo (Photo instance), commenter (User instance)
photo_commented = Signal()
