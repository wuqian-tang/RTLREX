"""Bounded Linux process-tree cancellation, including nested tool sessions.
Freeze each parent before enumerating children, so children cannot escape merely
by calling setsid(). Inspect every thread's children, since CEC launches tools
from worker threads. This module never searches or kills unrelated processes.
"""
import os,signal,subprocess
from pathlib import Path

def stop_tree(process):
 seen=set();order=[]
 def freeze(pid):
  if pid in seen:return
  seen.add(pid)
  try:os.kill(pid,signal.SIGSTOP)
  except ProcessLookupError:return
  order.append(pid)
  task=Path('/proc')/str(pid)/'task'
  try:threads=list(task.iterdir())
  except FileNotFoundError:return
  children=set()
  for thread in threads:
   try:children.update(map(int,(thread/'children').read_text().split()))
   except (FileNotFoundError,ProcessLookupError):pass
  for child in sorted(children):freeze(child)
 if not Path('/proc/self/task').is_dir():
  # This backend is explicitly Linux-only: do not silently claim descendant
  # cleanup on platforms that provide no process-tree traversal.
  raise RuntimeError('process-tree watchdog requires Linux /proc')
 freeze(process.pid)
 for pid in reversed(order):
  try:os.kill(pid,signal.SIGKILL)
  except ProcessLookupError:pass
 return order

def run(command,timeout):
 process=subprocess.Popen(command,text=True,stdout=subprocess.PIPE,stderr=subprocess.PIPE)
 try:stdout,stderr=process.communicate(timeout=timeout)
 except subprocess.TimeoutExpired:
  stop_tree(process);stdout,stderr=process.communicate();raise
 return subprocess.CompletedProcess(command,process.returncode,stdout,stderr)
