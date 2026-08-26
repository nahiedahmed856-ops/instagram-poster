"""
এই স্ক্রিপ্টটি আপনার পিসিতে একবার রান করে ইনস্টাগ্রামে লগইন করবেন।
এতে একটি 'session.json' ফাইল তৈরি হবে, যা পরবর্তীতে Render.com-এ ব্যবহার হবে।
বারবার লগইন করতে হবে না এবং ইনস্টাগ্রাম বট ব্লক করতে পারবে না।
"""
import os
import json
from instagrapi import Client

def generate_session():
    print("=" * 50)
    print("   INSTAGRAM SESSION GENERATOR (NO API NEEDED)   ")
    print("=" * 50)
    
    username = input("Enter your Instagram Username: ").strip()
    password = input("Enter your Instagram Password: ").strip()
    
    cl = Client()
    cl.delay_range = [2, 5]
    
    print("\n[+] Logging in... Please wait...")
    try:
        cl.login(username, password)
        cl.dump_settings("session.json")
        print("\n" + "=" * 50)
        print(" [SUCCESS] Logged in successfully!")
        print(" [SUCCESS] 'session.json' has been created.")
        print(" You can now upload this project to GitHub and Render.com")
        print("=" * 50)
    except Exception as e:
        print(f"\n[ERROR] Login failed: {e}")
        print("Note: If 2FA is enabled, turn off temporarily or approve from Instagram app notification.")

if __name__ == "__main__":
    generate_session()
