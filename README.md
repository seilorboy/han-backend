<h1>Energy Meter Reading &amp; Data Logging System</h1>

<p>
This project provides a complete solution for reading electric energy consumption from energy meters han/p1-port and storing the data in an SQL database.
</p>

<p>
It consists of two main components:
</p>

<ol>
  <li>Han-port readenr firmware for the Arduino Uno R4 WiFi board</li>
  <li>Docker-based backend datastorage running on Linux Debian</li>
</ol>

<hr>

<h2>Overview</h2>

<p>
The Arduino Uno R4 WiFi acts as a frontend device that communicates with electric energy meters and sends the readings to the backend API.
The backend application receives the measurements and stores them in an SQL database for further processing, analytics, or visualization.
</p>

<hr>

<h2>Features</h2>

<ul>
  <li>Reads electric energy consumption from supported meters</li>
  <li>Stores readings in an SQL database (MySQL/MariaDB)</li>
  <li>REST-style API endpoint for receiving measurement data</li>
  <li>Arduino sketch for the Uno R4 WiFi</li>
  <li>Docker-based backend and database services</li>
  <li>Works on Linux Debian</li>
  <li>Modular structure for future expansions (logging, dashboards, analytics)</li>
</ul>

<hr>

<h2>Components</h2>

<h3>1. Arduino Firmware</h3>

<p>
Folder: <code>arduino/</code>
</p>

<ul>
  <li>Written for Arduino Uno R4 WiFi</li>
  <li>Reads consumption data from HAN-port</li>
  <li>Sends data via HTTP POST to the backend API</li>
  <li>Includes WiFi setup and basic error handling</li>
</ul>

<h3>2. Docker Backend</h3>

<p>
Folder: <code>docker/</code>
</p>

<p>
Contains the following:
</p>

<ul>
  <li>Backend API (Flask or similar)</li>
  <li>MySQL/MariaDB database</li>
  <li>Optional Nginx or additional services</li>
</ul>

<p>Start the system with:</p>

<pre><code>docker compose up -d
</code></pre>

<hr>

<h2>Requirements</h2>

<h3>Hardware</h3>

<ul>
  <li>Arduino Uno R4 WiFi</li>
  <li>Electric energy meter with a compatible interface</li>
  <li>Linux Debian host or virtual machine</li>
  <li>Network connection (WiFi + LAN)</li>
</ul>

<h3>Software</h3>

<ul>
  <li>Docker and Docker Compose</li>
  <li>Arduino IDE 2.x</li>
  <li>Python 3.x (optional for development)</li>
</ul>

<hr>

<h2>Getting Started</h2>

<h3>1. Flash the Arduino</h3>

<ol>
  <li>Open Arduino IDE</li>
  <li>Load the sketch from the <code>arduino/</code> directory</li>
  <li>Configure WiFi credentials</li>
  <li>Upload the firmware to the Arduino Uno R4 WiFi</li>
</ol>

<h3>2. Start the Backend on Debian</h3>

<p>Clone the repository and start Docker services:</p>

<pre><code>git clone https://github.com/&lt;your-repo&gt;.git
cd docker
docker compose up -d
</code></pre>

<p>The API becomes available at:</p>

<pre><code>http://&lt;server-ip&gt;:8080/
</code></pre>

<hr>

<h2>Database Structure</h2>

<p>A new database Valkamakatu 11 added. It is having it's own setup file.</p>

<p>A typical measurement table:</p>

<table>
  <thead>
    <tr>
      <th>Column</th>
      <th>Type</th>
      <th>Description</th>
    </tr>
  </thead>
  <tbody>
    <tr>
      <td><code>id</code></td>
      <td>INT PK</td>
      <td>Unique identifier</td>
    </tr>
    <tr>
      <td><code>ts</code></td>
      <td>TIMESTAMP</td>
      <td>Timestamp of the measurement</td>
    </tr>
    <tr>
      <td><code>value_wh</code></td>
      <td>INT</td>
      <td>Measured energy in watt-hours</td>
    </tr>
    <tr>
      <td><code>meter_id</code></td>
      <td>INT</td>
      <td>Foreign key to the meters table</td>
    </tr>
  </tbody>
</table>

<hr>

<h2>Future Improvements</h2>

<ul>
  <li>Web dashboard for consumption visualization</li>
  <li>Support for additional meter types</li>
  <li>MQTT telemetry support</li>
  <li>Automatic firmware updates</li>
  <li>Detailed analytics and reporting features</li>
</ul>

<hr>

<h2>License</h2>

<p>
MIT License (or your preferred license)
</p>
