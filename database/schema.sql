-- CareConnect schema. Idempotent: the app runs this on first DB use (RDS is private).
-- The database itself (careconnect) is created by RDS.

CREATE TABLE IF NOT EXISTS users (
  id INT AUTO_INCREMENT PRIMARY KEY,
  name VARCHAR(100) NOT NULL,
  email VARCHAR(150) UNIQUE NOT NULL,
  password VARCHAR(255) NOT NULL,
  role VARCHAR(30) DEFAULT 'patient',
  created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS doctors (
  id INT AUTO_INCREMENT PRIMARY KEY,
  name VARCHAR(100) NOT NULL UNIQUE,
  specialization VARCHAR(100) NOT NULL,
  experience INT DEFAULT 0,
  available_days VARCHAR(100)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS appointments (
  id INT AUTO_INCREMENT PRIMARY KEY,
  patient_id INT NOT NULL,
  doctor_id INT NOT NULL,
  appointment_date DATETIME NOT NULL,
  reason VARCHAR(500),
  status VARCHAR(30) DEFAULT 'Booked',
  created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
  INDEX idx_patient_date (patient_id, appointment_date),
  INDEX idx_doctor_date (doctor_id, appointment_date),
  FOREIGN KEY (patient_id) REFERENCES users(id),
  FOREIGN KEY (doctor_id) REFERENCES doctors(id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS medications (
  id INT AUTO_INCREMENT PRIMARY KEY,
  patient_id INT NOT NULL,
  medicine VARCHAR(150) NOT NULL,
  dosage VARCHAR(100),
  schedule VARCHAR(100),
  created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
  INDEX idx_patient (patient_id),
  FOREIGN KEY (patient_id) REFERENCES users(id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

INSERT IGNORE INTO doctors (name, specialization, experience, available_days) VALUES
  ('Dr. Arun Kumar', 'General Medicine', 8, 'Mon,Wed,Fri'),
  ('Dr. Priya Sharma', 'Cardiology', 12, 'Tue,Thu,Sat'),
  ('Dr. Rahul Menon', 'Dermatology', 7, 'Mon,Thu,Fri'),
  ('Dr. Meera Nair', 'Pediatrics', 10, 'Mon,Tue,Wed'),
  ('Dr. Vikram Singh', 'Orthopedics', 15, 'Wed,Fri,Sat')
