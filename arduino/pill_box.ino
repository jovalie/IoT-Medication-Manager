// --- Configuration ---
const int reedPins[] = {2, 3, 4, 5, 6, 7, 8}; 
const int LED_PIN = 13; 
const int TOTAL_DAYS = 7;
const String dayNames[] = {"Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"};

// --- State Memory (The "Brain") ---
// Track if the pill has been taken for each day
#bool pillTaken[7] = {false, false, false, false, false, false, false};

// Track the current open/close status of each box to calculate duration
bool boxWasOpen[7] = {false, false, false, false, false, false, false};
unsigned long openStartTime[7] = {0, 0, 0, 0, 0, 0, 0};

void setup() {
  Serial.begin(9600);
  pinMode(LED_PIN, OUTPUT);

  for (int i = 0; i < TOTAL_DAYS; i++) {
    pinMode(reedPins[i], INPUT_PULLUP);
  }
  
  Serial.println("Smart Pillbox Tracker Started.");
  Serial.println("Waiting for activity...");
}

void loop() {
  // Check every single box in every loop
  for (int i = 0; i < TOTAL_DAYS; i++) {
    processDay(i);
  }
  
  delay(100); // Check 10 times a second
}

// --- The Logic Function ---
void processDay(int dayIndex) {
  // If we already took this pill, ignore this box!
  // if (pillTaken[dayIndex] == true) {
  //   return; 
  // }

  int pinState = digitalRead(reedPins[dayIndex]);

  if (pinState == HIGH) {
    
    // If it wasn't open before, this is the moment it opened
    if (!boxWasOpen[dayIndex]) {
      boxWasOpen[dayIndex] = true;
      openStartTime[dayIndex] = millis(); // Start the timer
      
      // --- NEW: SEND MESSAGE TO RASPBERRY PI ---
      Serial.print("OPENEVENT:");
      Serial.println(dayNames[dayIndex]); 
      // Output example: "OPENEVENT:Mon"
      // ----------------------------------------

      Serial.print(">> ");
      Serial.print(dayNames[dayIndex]);
      Serial.println(" opened...");
      digitalWrite(LED_PIN, HIGH); 
    }
  }
  
  // STATE 2: Box is currently CLOSED (Magnet Near -> LOW)
  else {
    
    // If it WAS open, this is the moment it closed
    if (boxWasOpen[dayIndex]) {
      boxWasOpen[dayIndex] = false; // Reset state
      digitalWrite(LED_PIN, LOW);   // Turn off light
      
      // Calculate how long it was open (in seconds)
      unsigned long duration = (millis() - openStartTime[dayIndex]) / 1000;
      
      Serial.print(">> ");
      Serial.print(dayNames[dayIndex]);
      Serial.print(" closed. Duration: ");
      Serial.print(duration);
      Serial.println("s");

      // VALIDATION: Only count if open for 2-60 seconds
      if (duration > 2 && duration < 60) {
        #pillTaken[dayIndex] = true; // MARK AS TAKEN
        Serial.print("SUCCESS: ");
        Serial.print(dayNames[dayIndex]);
        Serial.println(" pill logged as taken.");
      } else {
        Serial.println("IGNORED: Too fast to be a real dose.");
      }
    }
  }
}