// This branch is removed from production builds, including the inspector chunks.
if(process.env.NODE_ENV==='development'){
  await import('react-grab');
  const {scan}=await import('react-scan');
  scan({enabled:true,showToolbar:true});
}
