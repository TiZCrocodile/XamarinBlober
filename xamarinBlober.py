import struct
from pathlib import Path
import lz4.block
import sys
import xxhash

BLOB_MAGIC_BYTES = b'XABA'
COMPRESSED_ASSEMBLY_MAGIC_BYTES = b'XALZ'
supported_versions = [1]

def print_assemblies(assemblies):
	for assembly in assemblies:
		print(f'name:{assembly.name} | lec:{assembly.localStoreIndex} | offset:{assembly.dataOffset} | size:{assembly.dataSize} | hash32:{assembly.hash32}')

def error(s):
	print(s)
	exit(1)

def unpackUInt32LE(data):
	return struct.unpack('<I', data)[0]

def packUInt32LE(i):
	return struct.pack('<I',i)

def readUInt32(f):
	return struct.unpack('<I', f.read(4))[0]

def readUInt64(f):
	return struct.unpack('<Q', f.read(8))[0]

class AssemblyStoreAssembly():
	def __init__(self,localStoreIndex,dataOffset,dataSize,debugDataOffset,debugDataSize,configDataOffset,configDataSize):
		self.name = None
		self.localStoreIndex = localStoreIndex
		self.dataOffset = dataOffset
		self.dataSize = dataSize
		self.debugDataOffset = debugDataOffset
		self.debugDataSize = debugDataSize
		self.configDataOffset = configDataOffset
		self.configDataSize = configDataSize
		self.hash32 = None
		self.hash64 = None
		self.mappingIndex = None
		self.storeId = None

def readAssembliesManifest(filePath):
	assembliesIndexToName = {}
	
	with open(filePath,'r') as f:
		for line in f.read().split('\n')[1:]: # skip first line (Hash 32     Hash 64             Blob ID  Blob idx  Name)
			if line:
				# hash32,hash64,blobId,blobIndex,name
				_,_,_,blobIndex,name = line.split()
				blobIndex = int(blobIndex)
				assembliesIndexToName[blobIndex] = name
	
	return assembliesIndexToName

def readAssembliesBlobMetadata(filePath):
	assemblies = []
	
	with open(filePath,'rb') as f:
		magic_bytes = f.read(4) # magic number 'XABA'
		if magic_bytes != BLOB_MAGIC_BYTES:
			error(f"magic bytes should be '{BLOB_MAGIC_BYTES}', not '{magic_bytes}.'")
		
		version = readUInt32(f)
		if version not in supported_versions:
			error(f"magic bytes should be '{BLOB_MAGIC_BYTES}', not '{magic_bytes}.'")
		
		localEntryCount = readUInt32(f)
		globalEntryCount = readUInt32(f)
		storeId = readUInt32(f)
		
		for i in range(localEntryCount):
			assemblies.append(AssemblyStoreAssembly(i,readUInt32(f),readUInt32(f),readUInt32(f),readUInt32(f),readUInt32(f),readUInt32(f)))
		
		for _ in range(globalEntryCount):
			# hash32,mappingIndex,localStoreIndex,storeId
			hash32,mappingIndex,localStoreIndex,storeId = readUInt64(f),readUInt32(f),readUInt32(f),readUInt32(f)
			assemblies[localStoreIndex].hash32 = hash32
			assemblies[localStoreIndex].mappingIndex = mappingIndex
			assemblies[localStoreIndex].storeId = storeId
		
		for _ in range(globalEntryCount):
			# hash64,mappingIndex,localStoreIndex,storeId
			hash64,_,localStoreIndex,_ = readUInt64(f),readUInt32(f),readUInt32(f),readUInt32(f)
			assemblies[localStoreIndex].hash64 = hash64
		
		
	
	return assemblies	

def extractAssembliesBlob(assembliesBlobPath,assembliesManifestPath,outDir):
	assemblies = readAssembliesBlobMetadata(assembliesBlobPath)
	assembliesIndexToName = readAssembliesManifest(assembliesManifestPath)
	
	outDir = Path(outDir)
	outDir.mkdir(parents=True, exist_ok=True)
	
	with open(assembliesBlobPath,'rb') as assembliesBlob:
		for AssemblyIndex, assembly in enumerate(assemblies):
			assembliesBlob.seek(assembly.dataOffset)
			assemblyData = assembliesBlob.read(assembly.dataSize)
			if assemblyData.startswith(COMPRESSED_ASSEMBLY_MAGIC_BYTES):
				# compressed assembly, need to decompress it first
				decompressedAssemblySize = unpackUInt32LE(assemblyData[8:12])
				assemblyData = lz4.block.decompress(assemblyData[12:],uncompressed_size=decompressedAssemblySize)
			assemblyName = assembliesIndexToName[AssemblyIndex]
			assemblyPath = outDir / f'{assemblyName}.dll'
			with open(assemblyPath,'wb') as assemblyFile:
				assemblyFile.write(assemblyData)

def rebuildAssembliesBlob(assembliesBlobOutPath, assembliesManifestPath, assembliesDirPath):
	assembliesIndexToName = readAssembliesManifest(assembliesManifestPath)
	assembliesCount = len(assembliesIndexToName)
	assembliesDir = Path(assembliesDirPath)
	
	with open(assembliesBlobOutPath,'wb') as assembliesBlobOut:
		assembliesBlobOut.write(BLOB_MAGIC_BYTES) # magic bytes
		assembliesBlobOut.write(packUInt32LE(supported_versions[0])) # version
		assembliesBlobOut.write(packUInt32LE(assembliesCount)) # LocalEntryCount
		assembliesBlobOut.write(packUInt32LE(assembliesCount)) # GlobalEntryCount
		assembliesBlobOut.write(packUInt32LE(0)) # store id
		
		currentOffset = 20 + 64 * assembliesCount
		for index in assembliesIndexToName:
			assemblyFile = assembliesDir / f'{assembliesIndexToName[index]}.dll'
			assemblyFileSize = assemblyFile.stat().st_size
			assembliesBlobOut.write(packUInt32LE(currentOffset)) # DataOffset
			assembliesBlobOut.write(packUInt32LE(assemblyFileSize)) # DataSize
			assembliesBlobOut.write(packUInt32LE(0)) # DebugDataOffset
			assembliesBlobOut.write(packUInt32LE(0)) # DebugDataSize
			assembliesBlobOut.write(packUInt32LE(0)) # ConfigDataOffset
			assembliesBlobOut.write(packUInt32LE(0)) # ConfigDataSize
			currentOffset += assemblyFileSize
		
		for index in assembliesIndexToName:
			assembliesBlobOut.write(xxhash.xxh32(assembliesIndexToName[index]).digest()[::-1] + b'\x00\x00\x00\x00') # 32 bit hash (padded with 4 bytes of zeroes)
			assembliesBlobOut.write(packUInt32LE(index)) # MappingIndex
			assembliesBlobOut.write(packUInt32LE(index)) # LocalStoreIndex
			assembliesBlobOut.write(packUInt32LE(0)) # StoreID
		
		for index in assembliesIndexToName:
			assembliesBlobOut.write(xxhash.xxh64(assembliesIndexToName[index]).digest()[::-1]) # 64 bit hash
			assembliesBlobOut.write(packUInt32LE(index)) # MappingIndex
			assembliesBlobOut.write(packUInt32LE(index)) # LocalStoreIndex
			assembliesBlobOut.write(packUInt32LE(0)) # StoreID
		
		for index in assembliesIndexToName:
			assemblyFile = assembliesDir / f'{assembliesIndexToName[index]}.dll'
			with open(assemblyFile,'rb') as f:
				assembliesBlobOut.write(f.read())

mode = sys.argv[1]
assembliesBlobPath = sys.argv[2]
assembliesManifestPath = sys.argv[3]
assembliesDirPath = sys.argv[4]

if mode == 'unpack':
	extractAssembliesBlob(assembliesBlobPath,assembliesManifestPath,assembliesDirPath)
elif mode == 'pack':
	rebuildAssembliesBlob(assembliesBlobPath,assembliesManifestPath,assembliesDirPath)






