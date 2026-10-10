from fastapi import FastAPI,UploadFile,File,Body
from fastapi.responses import FileResponse,StreamingResponse,RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
import aiofiles
import asyncio
import json
from llm import chat_llm
import uvicorn
from chatbot import chatbot_followup
import uuid
from workflow import pipeline
import os
from s3_store import uploading_and_link

os.makedirs("uploads", exist_ok=True)
os.makedirs("outputs", exist_ok=True)

app=FastAPI()
app.mount("/templates",StaticFiles(directory="templates"))

jobs={}

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],  
)

@app.get("/")
def home():
    return FileResponse("templates/index.html")

@app.get("/sample_sales")
def get_sample():
    return FileResponse("templates/sample_sales.csv",media_type="text/csv",filename="sample_sales.csv")

async def workflow_runner(job_id: str, filepath: str):
    try:
        jobs[job_id]["status"] = "processing"
        config = {"configurable": {"thread_id": job_id}, "recursion_limit": 100}

        result = await asyncio.to_thread(
            pipeline.invoke,
            {'filepath': filepath},
            config=config
        )

        while True:
            state = await asyncio.to_thread(pipeline.get_state, config)
            next_nodes = list(state.next) if state and state.next else []
            
            print(f"\n{'='*70}")
            print(f"[STATUS CHECK] Next nodes: {next_nodes}")
            print(f"{'='*70}\n")

            if not next_nodes:
                print("[COMPLETE] No more nodes - workflow finished")
                break

            if "check_report" in next_nodes:
                print("[PAUSE] Waiting at check_report")
                jobs[job_id]["status"] = "pending_report"
                print(f"[STATUS_UPDATE] Set status to pending_report for {job_id}")
                if state and state.values:
                    jobs[job_id]["result"] = state.values
                else:
                    jobs[job_id]["result"] = result
                await jobs[job_id]["report_event"].wait()
                jobs[job_id]["report_event"].clear()
                
                approval = jobs[job_id]["approval_response"]
                print(f"[RECEIVED] Report approval: {approval}")

                jobs[job_id]["status"] = "processing"
                
                await asyncio.to_thread(
                    pipeline.update_state, 
                    config, 
                    {
                        "report_approved": approval["approved"], 
                        "report_feedback": approval.get("feedback", "")
                    }
                )
                
                print("[RESUME] Continuing pipeline after report approval...")
                result=await asyncio.to_thread(pipeline.invoke, None, config=config)
                print("[RESUMED] Pipeline continued")
                continue

            if "check_dashboard" in next_nodes:
                print("[PAUSE] Waiting at check_dashboard")
                jobs[job_id]["status"] = "pending_dashboard"
                print(f"[STATUS_UPDATE] Set status to pending_dashboard for {job_id}")
                if state and state.values:
                    jobs[job_id]["result"] = state.values
                    print(f"[DEBUG] Stored state values, keys: {list(state.values.keys())}")
                else:
                    jobs[job_id]["result"] = result
                
                await jobs[job_id]["dashboard_event"].wait()
                jobs[job_id]["dashboard_event"].clear()
                
                approval=jobs[job_id]["approval_response"]
                print(f"[RECEIVED] Dashboard approval: {approval}")
                
                jobs[job_id]["status"] = "processing"
                
                await asyncio.to_thread(
                    pipeline.update_state, 
                    config, 
                    {
                        "dashboard_approved": approval["approved"], 
                        "dashboard_feedback": approval.get("feedback", "")
                    }
                )
                print("[RESUME] Continuing pipeline after dashboard approval...")
                result = await asyncio.to_thread(pipeline.invoke, None, config=config)
                print("[RESUMED] Pipeline continued")
                continue

            print(f"[WARNING] Unexpected next nodes: {next_nodes}")
            break

        if isinstance(result, dict) and result.get('error'):
            jobs[job_id]["status"] = "failed"
            jobs[job_id]["result"] = result
            print(f"[ERROR] Pipeline encountered error: {result.get('error')}")
        else:
            jobs[job_id]["report_url"]=await asyncio.to_thread(uploading_and_link, "outputs/report.pdf", "application/pdf", f"outputs/{job_id}/report.pdf")
            jobs[job_id]["dashboard_url"]=await asyncio.to_thread(uploading_and_link, "outputs/dashboard.html", "text/html", f"outputs/{job_id}/dashboard.html")
            jobs[job_id]["status"]="completed"
            jobs[job_id]["result"]=result
            print(f"[SUCCESS] Job {job_id} completed successfully!")

    except Exception as e:
        jobs[job_id]["status"]="failed"
        jobs[job_id]["result"]={"error": str(e)}
        print(f"[ERROR] Job failed: {e}")
        import traceback
        traceback.print_exc()

@app.post("/upload")
async def analyze(data:UploadFile=File(...)):
    if not data.filename.endswith(".csv"):
        return {"error":"Invalid file format. Please upload csv file only."}
    job_id=str(uuid.uuid4())[:10]

    jobs[job_id]={
        "status": "uploading",
        "filepath": None,
        "result": None,
        "report_event": asyncio.Event(),
        "dashboard_event": asyncio.Event(),
        "approval_response": None,
        "chat_history":[]
    }

    FILEPATH=f"uploads/{data.filename}"
    async with aiofiles.open(FILEPATH,"wb") as buffer:
        await buffer.write(await data.read())
    
    asyncio.create_task(workflow_runner(job_id,FILEPATH))
    return {'job_id':job_id,'filepath':FILEPATH,'msg':'File uploaded successfully. Processing will begin shortly.'}

@app.get("/status/{job_id}")
def get_status(job_id:str):
    if job_id not in jobs:
        return {"error":"Invalid job ID.", "status":"failed"}
    status = jobs[job_id]["status"]
    response = {"job_id":job_id, "status": status}
    result = jobs[job_id].get("result", {})
    
    if isinstance(result, dict) and result.get('error'):
        response["status"] = "failed"
        response["error"] = result.get("error", "Unknown error occurred")
    elif status == "failed":
        response["error"] = result.get("error", "Unknown error occurred") if isinstance(result, dict) else "Pipeline failed"
    
    print(f"[STATUS] Job {job_id}: returning status={response['status']}")
    return response    

@app.get("/download_report/{job_id}")
async def download_report(job_id:str):
    if job_id not in jobs:
        return {"error":"Invalid job ID."}
    if jobs[job_id]["status"]!="completed":
        return {"error":"Job not completed yet."}
    if jobs[job_id].get("report_url"):
        return RedirectResponse(jobs[job_id]["report_url"])    
    report_path="outputs/report.pdf"
    return FileResponse(path=report_path, media_type="application/pdf", filename="report.pdf")

@app.get("/download_dashboard/{job_id}")
async def download_dashboard(job_id:str):
    if job_id not in jobs:
        return {"error":"Invalid job ID."}
    if jobs[job_id]["status"]!="completed":
        return {"error":"Job not completed yet."}
    if jobs[job_id].get("dashboard_url"):
        return RedirectResponse(jobs[job_id]["dashboard_url"])
    dashboard_path="outputs/dashboard.html"
    return FileResponse(path=dashboard_path, media_type="text/html", filename="dashboard.html")

@app.get("/stream/{job_id}")
async def stream_output(job_id:str):
    if job_id not in jobs:
        return {'error':"Invalid job ID."}
    async def event_generator():
        while True:
            status=jobs[job_id]['status']
            yield f"data:{json.dumps({'status': status})}\n\n"
            if status in ['completed','failed']:
                break
            await asyncio.sleep(2)
    return StreamingResponse(event_generator(),media_type="text/event-stream")

@app.get("/report/{job_id}")
async def get_report(job_id:str):
    if job_id not in jobs:
        return {'error':"Invalid job ID."}
    if jobs[job_id]['status'] not in ['pending_report','completed']:
        return {'error':"Report not ready yet."}
    report=jobs[job_id]["result"].get("report",{})
    return {"report":report}

@app.get("/dashboard/{job_id}")
async def get_dashboard(job_id:str):
    if job_id not in jobs:
        print(f"[DASHBOARD] Job {job_id} not found")
        return {'error':"Invalid job ID."}
    
    status = jobs[job_id]['status']
    print(f"[DASHBOARD] Job {job_id}: status={status}")
    
    if status not in ['pending_dashboard','completed']:
        print(f"[DASHBOARD] Job {job_id}: Dashboard not ready (status={status})")
        return {'error':"Dashboard not ready yet."}
    
    if status=='pending_dashboard':
        result=jobs[job_id]["result"]
        print(f"[DASHBOARD] Pending: result keys={list(result.keys()) if isinstance(result, dict) else 'not a dict'}")
        charts=result.get("charts", "No charts yet") if isinstance(result, dict) else "No charts yet"
        print(f"[DASHBOARD] Returning charts as {type(charts).__name__}: {charts[:100] if isinstance(charts, str) else 'not a string'}...")
        return {"dashboard": charts}
    
    dashboard=jobs[job_id]["result"].get("dashboard", {}) if isinstance(jobs[job_id]["result"], dict) else {}
    return {"dashboard":dashboard}

@app.post("/approve_report/{job_id}")
async def approve_report(job_id:str,approval:dict=Body(...)):
    feedback=approval.get("feedback","")
    approved=approval.get("approved",True)
    if job_id not in jobs:
        return {'error':"Invalid job ID."}
    if jobs[job_id]['status']!="pending_report":
        return {'error':"Report not ready for approval."}
    jobs[job_id]["approval_response"]={"approved": approved, "feedback": feedback}
    jobs[job_id]["report_event"].set()
    return {"msg":"Report approval received."}

@app.post("/approve_dashboard/{job_id}")
async def approve_dashboard(job_id:str,approval:dict=Body(...)):
    feedback=approval.get("feedback","")
    approved=approval.get("approved",True)
    if job_id not in jobs:
        return {'error':"Invalid job ID."}
    if jobs[job_id]['status']!="pending_dashboard":
        return {'error':"Dashboard not ready for approval."}
    jobs[job_id]["approval_response"]={"approved": approved, "feedback": feedback}
    jobs[job_id]["dashboard_event"].set()
    return {"msg":"Dashboard approval received."}
    
@app.post("/chat_with_argus/{job_id}")
def chat_with_argus(job_id:str,message:dict=Body(...)):
    if job_id not in jobs:
        return {'error':"Invalid job ID."}
    if jobs[job_id]['status']!="completed":
        return {'error':"Job not completed yet."}
    result=jobs[job_id]["result"]
    chat_history=jobs[job_id].setdefault("chat_history",[])
    user_message=message.get("message")
    reply=chatbot_followup(result,chat_llm,chat_history,user_message)
    return {"response":reply}

if __name__=="__main__":
    uvicorn.run(app,host="0.0.0.0",port=7860)

