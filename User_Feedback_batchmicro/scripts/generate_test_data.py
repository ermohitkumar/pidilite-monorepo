import os
import shutil
from gtts import gTTS

# Ensure test_files directory exists
os.makedirs("test_files", exist_ok=True)

print("Generating test files in 'test_files/' directory...")

# 1. Happy Path - Valid Audio (50+ words)
long_text = """
Hello! This is a comprehensive feedback session for Pidilite products. I have been using Fevicol SH for a long time and the bonding strength is excellent for all types of wood. However, recently I tried Fevikwik for a quick repair job, and while it works fast, the applicator could be improved because it gets clogged sometimes. The waterproofing solution Dr. Fixit LW+ was very effective during the monsoon season. Overall, these products are great, but some packaging improvements would be appreciated by all the carpenters and painters out here. Thank you for listening to my feedback. I hope this helps in improving the product experience.
"""
print("Generating Happy Path audio (this may take a few seconds)...")
tts_long = gTTS(text=long_text, lang='en')
long_filename_1 = "test_files/DecorativeWest_Mumbai_RFMM1_FME001_Painter.mp3"
tts_long.save(long_filename_1)

# Copy the same long audio for other tests that just need valid audio
shutil.copy(long_filename_1, "test_files/sample_audio.mp3")
shutil.copy(long_filename_1, "test_files/random_audio.mp3")
shutil.copy(long_filename_1, "test_files/audio.mp3")

# Non-ASCII filename
non_ascii_filename = "test_files/डेकोरेटिववेस्ट_मुंबई_RFMM1_FME001_Painter.mp3"
shutil.copy(long_filename_1, non_ascii_filename)

# 2. Fake Audio - Actually PDF
pdf_path = "test_files/fake_audio_actually_pdf.mp3"
with open(pdf_path, "wb") as f:
    f.write(b"%PDF-1.4\n% Fake PDF file for testing\n")

# 3. Fake Audio - Actually TXT
txt_path = "test_files/fake_audio_actually_txt.mp3"
with open(txt_path, "w") as f:
    f.write("This is a simple text file disguised as an MP3. STT should fail to decode this.")

# 4. 0-Byte File
zero_byte_path = "test_files/DecorativeWest_Mumbai_RFMM1_FME001_Painter_empty.mp3"
open(zero_byte_path, "w").close()

# 5. Short Audio (< 50 words)
short_text = "Hello. Yes. The Fevicol was very good. Goodbye."
print("Generating Short Audio...")
tts_short = gTTS(text=short_text, lang='en')
tts_short.save("test_files/short_audio.mp3")

# 6. Mixed Language Audio
mixed_text = "Namaste! Fevicol SH ka performance is absolutely fantastic. Its bonding is very majboot. Aamhi pan he vaparto, ani results khup changle ahet. But please improve the packaging. Dhanyawad!"
print("Generating Mixed Language Audio...")
tts_mixed = gTTS(text=mixed_text, lang='hi') # Using Hindi voice to read the mixed text
tts_mixed.save("test_files/mixed_language_audio.mp3")

print("All text-to-speech files generated successfully.")
