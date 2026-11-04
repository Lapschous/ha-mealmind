### Draft for Vision Pitch

#### **Hook**

- **Problem:** Students don't have the mental capacity to plan dinner, nor the cash to fund elaborate meals. The Home Assistant custom component *Mealmind* will free up mental bandwidth, keep users healthy, and save them money.
- **Gap:** Traditional smart home implementations force tradeoffs between privacy, latency, and capability. *Mealmind* addresses all these constraints by running on hardware that keeps data completely local, while remaining fully auditable as an open-source custom *Home Assistant* integration. Current solutions like *TheMealDB* are limited in recipe selection due to their for-profit structure, while integrations like *Mealie* don't adapt dynamically to user preferences.
- **Core Value:** A custom, open-source, fully local, and adaptable integration for *Home Assistant* that simplifies healthy eating for busy individuals.

#### **Solution and Technical Architecture**

- **Software Stack:** Python for backend server processing and custom Home Assistant integration logic. ESPHome for firmware on the ESP32-driven interaction satellite.
- **Hardware Interfacing:** A custom microcontroller-driven satellite acting as a physical portal to *Home Assistant* and *Mealmind*. The satellite listens for a custom wake word (e.g., "Hey Mealmind") and captures voice input (e.g., *"I'd like some Indian food tomorrow"*).
- **Ecosystem Integration:** Direct communication with *Home Assistant* via MQTT, Native API, or as a custom HACS (Home Assistant Community Store) integration.
- **Ai model** Mistral 3 8b Instruct 2512, FP8
   https://huggingface.co/mistralai/Ministral-3-8B-Instruct-2512

#### **Functionality**

- Return x amounts of recipes, for example if you want to shop for a week it returns 7
- Take both text and voice input
- Sends and recives messages via the <i></i>HA<i></i> app
- User should be able to review each recipe
- Local ai writes to a preferences file when reviews roll in
- Visualise the recipe database and add / edit recipes via the HA - app

#### **Hardware**

##### Server

- Mini PC (AMD Ryzen 6650H or 5400U, 16GB dual-channel RAM for fast local AI inference)

##### Satellite

- LilyGo T5 4.7" E-Paper V2.3 (ESP32-S3, Touch Version)
- INMP441 I2S Microphone module
- WS2812 LED ring (for visual feedback/status)
- Wires, USB-C cable, and 5V power adapter


#### **Skill Development**

- Neither of us currently has formal IoT or hardware development experience, making this a high-value project for technical growth. This initiative requires us to collect real data, structure databases, write backend business logic, and integrate physical hardware into a modern IoT ecosystem.

#### **Roadmap**

1. **Data Ingestion:** Populate the recipe database by aggregating and parsing recipe data.
2. **Backend Development:** Build the custom *Home Assistant* integration and connect the database.
   - Verify core functionality via standard manual triggers in the Home Assistant dashboard/app.
3. **Local AI Engine Pipeline:**
   - Configure local AI models to send automated daily recipe suggestions via Home Assistant notifications.
   - Process user feedback (e.g., *"I prefer option 2"*).
   - Return detailed ingredient lists and instructions.
4. **Hardware Satellite Assembly:**
   - Wire the microphone and LED status ring to the touchscreen e-paper display board.
   - Configure audio streaming via ESPHome to local Whisper/Piper pipelines for wake-word detection and voice parsing.
   - Mirrors all core touch and voice actions available in the Home Assistant app.
5. **Testing & Deployment:**
   - Deploy and live with the prototype for one month.
   - Document edge cases, latency bottlenecks, and grievances.
   - Refine codebase, polish UI, and publish as an open-source repository.
