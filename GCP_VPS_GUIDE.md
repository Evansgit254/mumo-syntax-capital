# How to Set Up a Windows VPS on Google Cloud Platform (GCP)

Since you already have a Google Cloud (GCP) account, you can deploy your trading bot there. 

> [!WARNING]
> **Important Cost Notice:** While GCP offers an "Always Free" `e2-micro` compute instance, **Windows Server licenses are NOT free on GCP**. 
> 
> Microsoft charges a premium for Windows Server OS images. Even if you use a small instance, running a Windows VM on GCP will typically cost **~$20 to $30 per month** due to licensing. If you want a 100% free Windows server, you must use AWS (see `AWS_VPS_GUIDE.md`). If you have GCP free credits ($300 trial) or are okay with the monthly cost, proceed below!

## Phase 1: Launching the Windows VM

1. **Go to Compute Engine**
   - In your GCP Console, search for **"Compute Engine"** and click on **VM instances**.
   - Click **Create Instance**.

2. **Configure the Instance**
   - **Name:** `mumo-trading-bot`
   - **Region:** Pick a region close to your broker's servers (e.g., London, New York) to minimize latency.
   - **Machine Configuration:** 
     - Series: **E2**
     - Machine type: **e2-small** (2 vCPU, 2 GB memory) or **e2-medium**. *Note: Windows Server requires at least 2GB of RAM to run smoothly; it cannot run on the free `e2-micro` (1GB).*

3. **Change the Boot Disk (Crucial!)**
   - Scroll down to "Boot disk" and click **Change**.
   - **Operating System:** Select **Windows Server**.
   - **Version:** Select **Windows Server 2022 Datacenter** (Desktop Experience). *Make sure it says "Desktop Experience", otherwise you won't get a graphical UI!*
   - **Boot disk size:** 50 GB.
   - Click **Select**.

4. **Firewall Settings**
   - You don't need HTTP/HTTPS traffic for the bot itself to connect to the broker, but checking them won't hurt.
   - RDP (Port 3389) is allowed by default in GCP to let you connect.

5. **Create!**
   - Click the blue **Create** button at the bottom. Wait 3-5 minutes for the VM to start.

---

## Phase 2: Connecting from your Mac

1. **Set your Windows Password**
   - Once the instance has a green checkmark next to it, click on the **Instance name** (`mumo-trading-bot`) to open its details.
   - At the top of the page, click the **Set Windows password** button.
   - Confirm your username (usually your Google account name).
   - GCP will generate a random password for you. **Copy this password immediately!** (You cannot see it again once you close the window).

2. **Download Microsoft Remote Desktop**
   - Open the **Mac App Store** and search for **"Microsoft Remote Desktop"** (the official app by Microsoft). Download and install it.

3. **Connect via RDP**
   - Go back to your GCP VM instances list and copy the **External IP** of your new VM.
   - Open the **Microsoft Remote Desktop** app on your Mac.
   - Click the **"+"** button at the top and select **"Add PC"**.
   - **PC name:** Paste your GCP **External IP** here.
   - Click **Add**.
   - Double-click the new PC icon that appears in the app.
   - It will ask for credentials. Enter the username you used in Step 1 and the generated password.
   - If you get a certificate warning, click **"Continue"**.

🎉 **You are now logged into your Windows VPS!**

---

## Phase 3: Moving the Bot to the Server

Now that you're on the Windows VPS, follow the **[VPS_DEPLOYMENT_GUIDE.md](file:///Users/kiplaa/Desktop/Projects/mumo-syntax-capital/VPS_DEPLOYMENT_GUIDE.md)**:

1. Copy-paste your zipped project folder directly from your Mac desktop into the Windows Remote Desktop window.
2. Open Microsoft Edge on the VPS and download/install **Python 3.10+**.
3. Install **MetaTrader 5** from your broker's website.
4. Run `start_vps.bat`!
