import pandas as pd
from sqlalchemy.orm import Session
from db.session import SessionLocal
from db.models import FeedbackTag
import sys

def seed_tags():
    file_path = '/Users/akshaymanjunath/Downloads/User Group Tag Description.xlsx'
    try:
        df = pd.read_excel(file_path)
    except Exception as e:
        print(f"Error reading excel file: {e}")
        sys.exit(1)

    db = SessionLocal()
    seen_tags = set()
    try:
        for index, row in df.iterrows():
            group = str(row['FEEDBACK GROUP']).strip() if pd.notna(row['FEEDBACK GROUP']) else None
            category = str(row['Feedback category']).strip() if pd.notna(row['Feedback category']) else None
            tags_raw = str(row['Feedback Tag']).strip() if pd.notna(row['Feedback Tag']) else None
            desc = str(row['Tag short description']).strip() if pd.notna(row['Tag short description']) else None

            if not tags_raw:
                continue

            # Split tags by comma
            tags = [t.strip() for t in tags_raw.split(',')]

            for tag_name in tags:
                if not tag_name or tag_name in seen_tags:
                    continue

                seen_tags.add(tag_name)
                existing_tag = db.query(FeedbackTag).filter(FeedbackTag.tag_name == tag_name).first()
                if existing_tag:
                    # Update description, group_type, category
                    existing_tag.description = desc
                    existing_tag.group_type = group
                    existing_tag.category = category
                    print(f"Updated tag: {tag_name}")
                else:
                    # Create new tag
                    new_tag = FeedbackTag(
                        tag_name=tag_name,
                        description=desc,
                        group_type=group,
                        category=category
                    )
                    db.add(new_tag)
                    print(f"Created tag: {tag_name}")

        db.commit()
        print("Successfully seeded all tags!")

    except Exception as e:
        print(f"Database error: {e}")
        db.rollback()
    finally:
        db.close()

if __name__ == '__main__':
    seed_tags()
